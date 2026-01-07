/*
* DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
* Copyright (C) 2026, Slinky Software
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU General Public License as published by
* the Free Software Foundation, either version 3 of the License, or
* (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU General Public License for more details.
*
* You should have received a copy of the GNU General Public License
* along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/

export default function (ctx) {
  return {
    boot: [],
    css: ['app.css'],
    extras: [
      'material-icons'
    ],
    build: {
      vueRouterMode: 'history',
      extendViteConf(viteConf) {
        viteConf.server = viteConf.server || {};
        viteConf.server.port = 9000;
        viteConf.server.host = '0.0.0.0';
        viteConf.server.allowedHosts = true;
      }
    },
    devServer: {
      port: 9000,
      host: '0.0.0.0',
      open: false
    },
    framework: {
      config: {},
      plugins: ['Notify', 'Dialog'],
      components: [
        'QLayout',
        'QHeader',
        'QDrawer',
        'QPageContainer',
        'QPage',
        'QToolbar',
        'QToolbarTitle',
        'QBtn',
        'QBtnDropdown',
        'QIcon',
        'QAvatar',
        'QList',
        'QItem',
        'QItemSection',
        'QItemLabel',
        'QSeparator',
        'QMenu',
        'QSpace',
        'QCard',
        'QCardSection',
        'QBanner',
        'QInput',
        'QCheckbox',
        'QTable',
        'QTd',
        'QForm',
        'QDialog',
        'QBadge'
      ]
    }
  }
}
