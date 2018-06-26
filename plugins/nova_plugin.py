#!/usr/bin/env python
#
# vim: tabstop=4 shiftwidth=4

# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; only version 2 of the License is applicable.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#
# Authors:
#   Ricardo Rocha <ricardo@catalyst.net.nz>
#
# About this plugin:
#   This plugin collects OpenStack nova information, including limits and
#   quotas per tenant.
#
# collectd:
#   http://collectd.org
# OpenStack Nova:
#   http://docs.openstack.org/developer/nova
# collectd-python:
#   http://collectd.org/documentation/manpages/collectd-python.5.shtml
#
from novaclient.client import Client as NovaClient
from novaclient import exceptions
from keystoneclient.v3 import client as KeystoneClient

import collectd
import traceback

import base

class NovaPlugin(base.Base):

    def __init__(self):
        base.Base.__init__(self)
        self.prefix = 'openstack-nova'
        self.keystone = None
        self.nova = None

    def get_stats(self):
        if self.keystone_version == 'v2':
            return self._v2_get_stats()
        else:
            return self._v3_get_stats()

    def _get_keystone(self):
        if self.keystone is None:
            if self.region is None:
                self.keystone = KeystoneClient.Client(session=self.get_session())
            else:
                self.keystone = KeystoneClient.Client(session=self.get_session(), region_name=self.region)
        return self.keystone

    def _get_nova(self):
        if self.nova is None:
            if self.region is None:
                self.nova = NovaClient(2, session=self.get_session())
            else:
                self.nova = NovaClient(2, session=self.get_session(), region_name=self.region)
        return self.nova

    def _v3_get_stats(self):
        data = { self.prefix: {} }
        keystone = self._get_keystone()
        nova = self._get_nova()

        if self.notenants == False:
            project_list = keystone.projects.list()
            for project in project_list:
                data_project = { 'limits': {}, 'quotas': {} }

                # Get absolute limits for project
                limits = nova.limits.get(tenant_id=project.id).absolute
                for limit in limits:
                    data_project['limits'][limit.name] = limit.value

                # Quotas for project
                quotas = nova.quotas.get(project.id).to_dict()
                del quotas['id']
                data_project['quotas'] = quotas

                data[self.prefix]["project-%s" % project.name] = data_project

        # Hypervisor information
        hypervisors = nova.hypervisors.list()
        for hypervisor in hypervisors:
            name = "hypervisor-%s" % hypervisor.hypervisor_hostname
            data[self.prefix][name] = {}
            for item in ('current_workload', 'disk_available_least', 'free_disk_gb', 'free_ram_mb',
                    'hypervisor_version', 'memory_mb', 'memory_mb_used',
                    'running_vms', 'vcpus', 'vcpus_used', 'local_gb', 'local_gb_used'):
                data[self.prefix][name][item] = getattr(hypervisor, item)

        return data

    def _v2_get_stats(self):
        """Retrieves stats from nova"""
        keystone = self.get_keystone()

        data = { self.prefix: { 'cluster': { 'config': {} }, } }
        if getattr(self, 'region') is None:
            client = NovaClient('2', self.username, self.password, self.tenant, self.auth_url)
        else:
            client = NovaClient('2', self.username, self.password, self.tenant, self.auth_url,
                                region_name=self.region)

        if getattr(self, 'notenants') == False:
            tenant_list = keystone.tenants.list()

            for tenant in tenant_list:
                # FIX: nasty but works for now (tenant.id not being taken below :()
                client.tenant_id = tenant.id
                data[self.prefix]["tenant-%s" % tenant.name] = { 'limits': {}, 'quotas': {} }
                data_tenant = data[self.prefix]["tenant-%s" % tenant.name]

                # Get absolute limits for tenant
                limits = client.limits.get(tenant_id=tenant.id).absolute
                for limit in limits:
                    if 'ram' in limit.name.lower():
                        limit.value = limit.value * 1024.0 * 1024.0
                    data_tenant['limits'][limit.name] = limit.value

                # Quotas for tenant
                quotas = client.quotas.get(tenant.id)
                for item in ('cores', 'fixed_ips', 'floating_ips', 'instances',
                    'key_pairs', 'ram', 'security_groups'):
                    if item == 'ram':
                        setattr(quotas, item, getattr(quotas, item) * 1024 * 1024)
                    data_tenant['quotas'][item] = getattr(quotas, item)

        # Cluster allocation / reserved values
        for item in ('AllocationRatioCores', 'AllocationRatioRam',
                'ReservedNodeCores', 'ReservedNodeRamMB',
                'ReservedCores', 'ReservedRamMB'):
            data[self.prefix]['cluster']['config'][item] = getattr(self, item)

        # Hypervisor information
        hypervisors = client.hypervisors.list()
        for hypervisor in hypervisors:
            name = "hypervisor-%s" % hypervisor.hypervisor_hostname
            data[self.prefix][name] = {}
            for item in ('current_workload', 'free_disk_gb', 'free_ram_mb',
                    'hypervisor_version', 'memory_mb', 'memory_mb_used',
                    'running_vms', 'vcpus', 'vcpus_used'):
                data[self.prefix][name][item] = getattr(hypervisor, item)
            data[self.prefix][name]['memory_mb_overcommit'] = \
                data[self.prefix][name]['memory_mb'] * data[self.prefix]['cluster']['config']['AllocationRatioRam']
            data[self.prefix][name]['memory_mb_overcommit_withreserve'] = \
                data[self.prefix][name]['memory_mb_overcommit'] - data[self.prefix]['cluster']['config']['ReservedNodeRamMB']
            data[self.prefix][name]['vcpus_overcommit'] = \
                data[self.prefix][name]['vcpus'] * data[self.prefix]['cluster']['config']['AllocationRatioCores']
            data[self.prefix][name]['vcpus_overcommit_withreserve'] = \
                data[self.prefix][name]['vcpus_overcommit'] - data[self.prefix]['cluster']['config']['ReservedNodeCores']

        # NOTE(flwang): Below data will do the similar thing as above, but only
        # for windows host.
        aggregates = client.aggregates.list()
        for aggregate in aggregates:
            if aggregate.metadata.get('os_distro', None) == 'windows':
                for host in aggregate.hosts:
                    for hypervisor in hypervisors:
                        if hypervisor.hypervisor_hostname.startswith(host):
                            name = "windows-hypervisor-%s" % hypervisor.hypervisor_hostname
                            data[self.prefix][name] = {}
                            for item in ('current_workload', 'free_disk_gb', 'free_ram_mb',
                                    'hypervisor_version', 'memory_mb', 'memory_mb_used',
                                    'running_vms', 'vcpus', 'vcpus_used'):
                                data[self.prefix][name][item] = getattr(hypervisor, item)
                            data[self.prefix][name]['memory_mb_overcommit'] = \
                                data[self.prefix][name]['memory_mb'] * data[self.prefix]['cluster']['config']['AllocationRatioRam']
                            data[self.prefix][name]['memory_mb_overcommit_withreserve'] = \
                                data[self.prefix][name]['memory_mb_overcommit'] - data[self.prefix]['cluster']['config']['ReservedNodeRamMB']
                            data[self.prefix][name]['vcpus_overcommit'] = \
                                data[self.prefix][name]['vcpus'] * data[self.prefix]['cluster']['config']['AllocationRatioCores']
                            data[self.prefix][name]['vcpus_overcommit_withreserve'] = \
                                data[self.prefix][name]['vcpus_overcommit'] - data[self.prefix]['cluster']['config']['ReservedNodeCores']

        return data

try:
    plugin = NovaPlugin()
except Exception as exc:
    collectd.error("openstack-nova: failed to initialize nova plugin :: %s :: %s"
            % (exc, traceback.format_exc()))

def configure_callback(conf):
    """Received configuration information"""
    plugin.config_callback(conf)

def read_callback():
    """Callback triggerred by collectd on read"""
    plugin.read_callback()

collectd.register_config(configure_callback)
collectd.register_read(read_callback, plugin.interval)
