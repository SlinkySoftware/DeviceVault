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
        viteConf.server.allowedHosts = [PLACEHOLDER_ALLOWED_HOSTS];
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
        'QIcon',
        'QList',
        'QItem',
        'QItemSection',
        'QItemLabel',
        'QCard',
        'QCardSection',
        'QInput',
        'QTable',
        'QTd',
        'QForm'
      ]
    }
  }
}
