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
#   This plugin collects OpenStack keystone information, including totals
#   for services, tenants, roles, etc, and per tenant user count.
#
# collectd:
#   http://collectd.org
# OpenStack Keystone:
#   http://docs.openstack.org/developer/keystone
# collectd-python:
#   http://collectd.org/documentation/manpages/collectd-python.5.shtml
#
import collectd
import traceback
from keystoneclient.v3 import client as KeystoneClient

import base

class KeystonePlugin(base.Base):

    def __init__(self):
        base.Base.__init__(self)
        self.prefix = 'openstack-keystone'
        self.keystone = None

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

    def _v3_get_stats(self):
        """Retrieves stats from keystone via API-v3"""
        keystone = self._get_keystone()
        data = { self.prefix: { 'totals': {
            'projects': 0, 'users': 0, 'roles': 0, 'services': 0, 'endpoints': 0
        } } }

        for item in data[self.prefix]['totals'].keys():
            data[self.prefix]['totals'][item] = {
                'count': len(keystone.__getattribute__(item).list())
            }

        if getattr(self, 'notenants') == False:
            project_list = keystone.projects.list()
            for project in project_list:
                k = "project-%s" % project.name
                data[self.prefix][k] = { 'users': {
                    'count': len(keystone.users.list(default_project=project.id))
                    } }
        return data

    def _v2_get_stats(self):
        """Retrieves stats from keystone"""
        keystone = self.get_keystone()

        data = { self.prefix: {} }

        # Total for usual keystone stats
        data[self.prefix]['totals'] = { 
          'tenants': 0, 'users': 'users', 'roles': 0, 'services': 0, 'endpoints': 0 }
        for item in ('tenants', 'users', 'roles', 'services', 'endpoints'):
            data[self.prefix]['totals'][item] = { 
                'count': len(keystone.__getattribute__(item).list())
            }

        if getattr(self, 'notenants') == False:
            # User count per tenant
            tenant_list = keystone.tenants.list()
            for tenant in tenant_list:
                data[self.prefix]["tenant-%s" % tenant.name] = { 'users': {} }
                data_tenant = data[self.prefix]["tenant-%s" % tenant.name]
                data_tenant['users']['count'] = len(keystone.tenants.list_users(tenant.id))

        return data

try:
    plugin = KeystonePlugin()
except Exception as exc:
    collectd.error("openstack-keystone: failed to initialize keystone plugin :: %s :: %s"
            % (exc, traceback.format_exc()))
    
def configure_callback(conf):
    """Received configuration information"""
    plugin.config_callback(conf)

def read_callback():
    """Callback triggerred by collectd on read"""
    plugin.read_callback()

collectd.register_config(configure_callback)
collectd.register_read(read_callback, plugin.interval)
