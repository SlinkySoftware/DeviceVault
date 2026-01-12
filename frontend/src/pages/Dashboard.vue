<template>
  <q-page class="q-pa-sm dashboard-page">
    <div class="row items-center q-mb-md">
      <div class="col text-h4">Dashboard</div>
    </div>

    <div class="dashboard-grid">
      <div 
        v-for="widget in orderedWidgets" 
        :key="widget.id" 
        :class="getWidgetClass(widget)"
        :style="getWidgetStyle(widget)"
      >
        <q-card class="full-height widget-card">
          <q-card-section class="q-py-sm widget-title">
            <div class="text-h6 text-weight-bold">{{ widget.title }}</div>
          </q-card-section>
          <q-separator />
          <q-card-section class="q-pa-sm widget-content">
            <component :is="widget.component" :stats="stats" />
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script>
import { defineComponent, h } from 'vue'
import { QIcon } from 'quasar'
import api from '../services/api'

// Widget components - using render functions instead of templates
const ConfiguredDevicesWidget = defineComponent({
  props: ['stats'],
  computed: {
    totalDevices() {
      return Object.values(this.stats?.devicesByType || {}).reduce((a, b) => a + (b.count || b), 0)
    }
  },
  render() {
    return h('div', { class: 'q-gutter-md q-pa-sm', style: { height: '100%', display: 'flex', flexDirection: 'column' } }, [
      h('div', { class: 'row q-col-gutter-md', style: { flex: 1 } }, [
        h('div', { class: 'col-5', style: { display: 'flex' } }, [
          h('div', { style: { border: '3px solid var(--theme-dashboard-nested-box, #2196F3)', borderRadius: '8px', padding: '18px 20px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', flex: 1 } }, [
            h('div', { class: 'text-subtitle2 text-weight-medium', style: { fontSize: '0.875rem', marginBottom: '8px' } }, 'Total'),
            h('div', { 
              class: 'text-primary text-weight-bold',
              style: { fontSize: 'clamp(3rem, 15vw, 8rem)', lineHeight: '1' }
            }, this.totalDevices.toString())
          ])
        ]),
        h('div', { class: 'col-7', style: { display: 'flex', flexDirection: 'column', gap: '8px' } }, [
          ...Object.entries(this.stats?.devicesByType || {}).map(([type, data]) => {
            const count = data.count || data
            const icon = data.icon || 'router'
            return h('div', { style: { border: '3px solid var(--theme-dashboard-nested-box, #2196F3)', borderRadius: '8px', padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '12px' }, key: type }, [
              h(QIcon, { name: icon, size: 'md', color: 'primary' }),
              h('div', { class: 'flex-1' }, [
                h('div', { class: 'text-subtitle2 text-grey' }, type),
                h('div', { class: 'text-h5 text-weight-medium text-primary' }, count.toString())
              ])
            ])
          }),
          Object.keys(this.stats?.devicesByType || {}).length === 0
            ? h('div', { class: 'text-caption text-grey' }, 'No devices')
            : null
        ])
      ])
    ])
  }
})

const BackupsWidget = defineComponent({
  props: ['stats'],
  render() {
    return h('div', { class: 'row q-col-gutter-md q-pa-sm', style: { height: '100%' } }, [
      h('div', { class: 'col-6', style: { display: 'flex' } }, [
        h('div', { style: { border: '3px solid var(--theme-dashboard-nested-box, #2196F3)', borderRadius: '8px', padding: '18px 20px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', flex: 1 } }, [
          h('div', { class: 'text-subtitle2 text-weight-medium', style: { fontSize: '1rem', marginBottom: '8px' } }, 'Success'),
          h('div', { 
            class: 'text-positive text-weight-bold',
            style: { fontSize: 'clamp(3rem, 15vw, 8rem)', lineHeight: '1' }
          }, (this.stats?.success24h || 0).toString())
        ])
      ]),
      h('div', { class: 'col-6', style: { display: 'flex' } }, [
        h('div', { style: { border: '3px solid var(--theme-dashboard-nested-box, #2196F3)', borderRadius: '8px', padding: '18px 20px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', flex: 1 } }, [
          h('div', { class: 'text-subtitle2 text-weight-medium', style: { fontSize: '1rem', marginBottom: '8px' } }, 'Failed'),
          h('div', { 
            class: 'text-negative text-weight-bold',
            style: { fontSize: 'clamp(3rem, 15vw, 8rem)', lineHeight: '1' }
          }, (this.stats?.failed24h || 0).toString())
        ])
      ])
    ])
  }
})

const AvgTimeWidget = defineComponent({
  props: ['stats'],
  render() {
    return h('div', { 
      class: 'full-height flex flex-center',
      style: { padding: '20px' }
    }, [
      h('div', { 
        class: 'text-primary text-weight-bold dynamic-text',
        style: { fontSize: 'clamp(3rem, 15vw, 8rem)', lineHeight: '1.2' }
      }, (this.stats?.avgDuration || 0) + 's')
    ])
  }
})

const SuccessRateWidget = defineComponent({
  props: ['stats'],
  render() {
    const rate = this.stats?.successRate || 0
    return h('div', { 
      class: 'full-height flex flex-center',
      style: { padding: '20px' }
    }, [
      h('div', { 
        class: 'text-positive text-weight-bold dynamic-text',
        style: { fontSize: 'clamp(3rem, 15vw, 8rem)', lineHeight: '1.2' }
      }, rate + '%')
    ])
  }
})

const ChartWidget = defineComponent({
  props: ['stats'],
  data() {
    return {
      observer: null,
      resizeObserver: null
    }
  },
  mounted() {
    this.$nextTick(() => this.renderChart())
    // Watch for dark mode changes via MutationObserver
    this.observer = new MutationObserver(() => {
      this.renderChart()
    })
    this.observer.observe(document.body, {
      attributes: true,
      attributeFilter: ['class']
    })
    // Watch for container resize
    if (this.$refs.chartCanvas) {
      this.resizeObserver = new ResizeObserver(() => {
        this.renderChart()
      })
      this.resizeObserver.observe(this.$refs.chartCanvas.parentElement)
    }
  },
  beforeUnmount() {
    if (this.observer) {
      this.observer.disconnect()
    }
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
    }
  },
  updated() {
    this.renderChart()
  },
  methods: {
    isDarkMode() {
      return document.body.classList.contains('body--dark')
    },
    renderChart() {
      if (!this.$refs.chartCanvas) return
      const ctx = this.$refs.chartCanvas.getContext('2d')
      const container = this.$refs.chartCanvas.parentElement
      // Get actual container dimensions
      const containerRect = container.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      const width = containerRect.width
      const height = containerRect.height
      // Set canvas size with device pixel ratio for crisp rendering
      this.$refs.chartCanvas.width = width * dpr
      this.$refs.chartCanvas.height = height * dpr
      this.$refs.chartCanvas.style.width = width + 'px'
      this.$refs.chartCanvas.style.height = height + 'px'
      ctx.scale(dpr, dpr)
      ctx.clearRect(0, 0, width, height)
      const dailyStats = this.stats.dailyStats || []
      if (dailyStats.length === 0) return
      const padding = { left: 40, right: 40, top: 40, bottom: 40 }
      const chartWidth = width - padding.left - padding.right
      const chartHeight = height - padding.top - padding.bottom
      const xStep = chartWidth / (dailyStats.length - 1)
      const textColor = this.isDarkMode() ? '#fff' : '#000'
      const lineColor = this.isDarkMode() ? '#1976D2' : '#1976D2'
      const gridColor = this.isDarkMode() ? '#333' : '#eee'
      
      // Draw y-axis scale and grid lines
      ctx.font = '14px sans-serif'
      ctx.fillStyle = textColor
      ctx.textAlign = 'right'
      const yLabels = [0, 25, 50, 75, 100]
      yLabels.forEach(percent => {
        const y = height - padding.bottom - (percent / 100) * chartHeight
        // Draw label
        ctx.fillText(`${percent}%`, padding.left - 8, y + 3)
        // Draw grid line
        ctx.strokeStyle = gridColor
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(padding.left, y)
        ctx.lineTo(width - padding.right, y)
        ctx.stroke()
      })
      
      // Draw axes
      ctx.strokeStyle = this.isDarkMode() ? '#555' : '#ccc'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(padding.left, height - padding.bottom)
      ctx.lineTo(width - padding.right, height - padding.bottom)
      ctx.moveTo(padding.left, padding.top)
      ctx.lineTo(padding.left, height - padding.bottom)
      ctx.stroke()
      
      // Draw spline/curved line and points
      ctx.strokeStyle = lineColor
      ctx.lineWidth = 2
      ctx.beginPath()
      
      const points = dailyStats.map((day, index) => ({
        x: padding.left + index * xStep,
        y: height - padding.bottom - (day.rate / 100) * chartHeight
      }))
      
      if (points.length > 0) {
        ctx.moveTo(points[0].x, points[0].y)
        
        for (let i = 1; i < points.length; i++) {
          const cp1x = points[i - 1].x + (points[i].x - points[i - 1].x) / 2
          const cp1y = points[i - 1].y
          const cp2x = points[i - 1].x + (points[i].x - points[i - 1].x) / 2
          const cp2y = points[i].y
          
          ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, points[i].x, points[i].y)
        }
      }
      ctx.stroke()
      
      // Draw points and labels
      ctx.font = '15px sans-serif'
      ctx.textAlign = 'center'
      dailyStats.forEach((day, index) => {
        const x = padding.left + index * xStep
        const y = height - padding.bottom - (day.rate / 100) * chartHeight
        
        // Draw point
        const color = day.rate >= 80 ? '#21BA45' : day.rate >= 50 ? '#F2C037' : '#C10015'
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(x, y, 5, 0, Math.PI * 2)
        ctx.fill()
        
        // Draw value label above point
        ctx.fillStyle = textColor
        ctx.fillText(`${Math.round(day.rate)}%`, x, y - 12)
        
        // Draw day label below axis
        const label = new Date(day.date).toLocaleDateString('en-US', { weekday: 'short' })
        ctx.fillText(label, x, height - padding.bottom + 20)
      })
    }
  },
  render() {
    return h('div', { class: 'chart-container', style: { width: '100%', height: '100%' } }, [
      h('canvas', { ref: 'chartCanvas', style: { display: 'block', width: '100%', height: '100%' } })
    ])
  }
})

const ActivityWidget = defineComponent({
  props: ['stats'],
  data() {
    return { recentActivity: [], interval: null, refreshMs: 30000 }
  },
  mounted() {
    this.loadActivity()
    this.setRefresh()
  },
  beforeUnmount() {
    if (this.interval) {
      clearInterval(this.interval)
    }
  },
  methods: {
    async loadActivity() {
      try {
        const res = await api.get('/recent-backup-activity/?limit=15')
        this.recentActivity = Array.isArray(res.data) ? res.data : res.data.results || []
        // Adjust refresh cadence: faster when any backups are in progress
        const hasInProgress = this.recentActivity.some(item => item.status === 'in_progress' || item.status === 'pending')
        this.refreshMs = hasInProgress ? 5000 : 30000
        this.setRefresh()
      } catch (e) {
        this.recentActivity = []
      }
    },
    setRefresh() {
      if (this.interval) {
        clearInterval(this.interval)
      }
      this.interval = setInterval(() => this.loadActivity(), this.refreshMs)
    },
    formatDate(dateStr) {
      if (!dateStr) return ''
      const date = new Date(dateStr)
      const now = new Date()
      const diffMs = now - date
      const diffMins = Math.floor(diffMs / 60000)
      const diffHours = Math.floor(diffMs / 3600000)
      
      if (diffMins < 1) return 'Just now'
      if (diffMins < 60) return `${diffMins}m ago`
      if (diffHours < 24) return `${diffHours}h ago`
      return date.toLocaleDateString()
    },
    getStatusColor(status) {
      if (status === 'success') return 'positive'
      if (status === 'failed') return 'negative'
      if (status === 'pending' || status === 'in_progress') return 'warning'
      return 'grey'
    },
    getStatusIcon(status) {
      if (status === 'success') return 'check_circle'
      if (status === 'failed') return 'error'
      if (status === 'pending' || status === 'in_progress') return 'autorenew'
      return 'info'
    },
    getIconClass(status) {
      return (status === 'in_progress' || status === 'pending') ? 'pulse-icon' : ''
    },
    formatSize(bytes) {
      if (!bytes) return ''
      if (bytes < 1024) return `${bytes} B`
      if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
      return `${(bytes / 1048576).toFixed(1)} MB`
    }
  },
  render() {
    return h('div', { class: 'q-pa-sm', style: 'max-height: 300px; overflow-y: auto' }, [
      ...(this.recentActivity.length > 0
        ? this.recentActivity.map(item =>
            h('div', { key: item.id, class: 'row items-center activity-row q-px-md q-py-xs' }, [
              h('div', { class: 'col-5', style: { fontSize: '1.5rem', fontWeight: 'bold' } }, item.device_name),
              h('div', { class: 'col-3', style: { fontSize: '1.25rem' } }, this.formatDate(item.timestamp)),
              h('div', { class: 'col-2', style: { fontSize: '1.25rem' } }, item.duration ? `${item.duration}s` : ''),
              h('div', { class: 'col-2 row items-center', style: { fontSize: '1.25rem' } }, [
                h(QIcon, { 
                  name: this.getStatusIcon(item.status),
                  color: this.getStatusColor(item.status),
                  class: this.getIconClass(item.status),
                  size: 'lg'
                }),
                h('span', { class: 'q-ml-xs' }, item.status_display || item.status)
              ])
            ])
          )
        : [h('div', { style: { fontSize: '1.25rem', padding: '16px' } }, 'No recent backup activity')])
    ])
  }
})

export default defineComponent({
  name: 'DashboardPage',
  components: {
    ConfiguredDevicesWidget,
    BackupsWidget,
    AvgTimeWidget,
    SuccessRateWidget,
    ChartWidget,
    ActivityWidget
  },
  data() {
    const defaultWidgets = [
      { id: 'devices', width: 3, height: 220 },
      { id: 'backups', width: 3, height: 220 },
      { id: 'avgtime', width: 3, height: 220 },
      { id: 'successrate', width: 3, height: 440 },
      { id: 'chart', width: 6, height: 120 },
      { id: 'activity', width: 6, height: 150 }
    ]

    return {
      stats: { devicesByType: {}, success24h: 0, failed24h: 0, avgDuration: 0, dailyStats: [] },
      defaultOrder: defaultWidgets,
      widgetOrder: [...defaultWidgets]
    }
  },
  computed: {
    orderedWidgets() {
      const widgetMap = {
        devices: { id: 'devices', title: 'Configured Devices', component: ConfiguredDevicesWidget },
        backups: { id: 'backups', title: 'Backups (24h)', component: BackupsWidget },
        avgtime: { id: 'avgtime', title: 'Avg Backup Time', component: AvgTimeWidget },
        successrate: { id: 'successrate', title: 'Device Success Rate', component: SuccessRateWidget },
        chart: { id: 'chart', title: 'Backup Success Rate (Last 7 Days)', component: ChartWidget },
        activity: { id: 'activity', title: 'Recent Backup Activity', component: ActivityWidget }
      }

      return this.widgetOrder
        .map(widget => {
          const widgetConfig = widgetMap[widget.id]
          if (!widgetConfig) return null

          const defaultHeight =
            widget.id === 'chart' || widget.id === 'activity'
              ? 300
              : widget.id === 'successrate'
              ? 440
              : 220

          return {
            ...widgetConfig,
            width: widget.width || (widget.id === 'chart' || widget.id === 'activity' ? 12 : 3),
            height: widget.height || defaultHeight
          }
        })
        .filter(w => w)
    }
  },
  methods: {
    getWidgetClass() {
      return 'dashboard-widget'
    },
    getWidgetStyle(widget) {
      const width = Math.max(1, Math.min(12, widget.width || (widget.id === 'chart' || widget.id === 'activity' ? 12 : 3)))
      const height =
        widget.height ||
        (widget.id === 'chart' || widget.id === 'activity'
          ? 300
          : widget.id === 'successrate'
          ? 440
          : 220)

      return {
        gridColumn: `span ${width}`,
        minHeight: `${height}px`
      }
    },
    async loadData() {
      try {
        const res = await api.get('/dashboard-stats/')
        this.stats = res.data || this.stats
        this.widgetOrder = [...this.defaultOrder]
      } catch (e) {
        this.stats = { devicesByType: {}, success24h: 0, failed24h: 0, avgDuration: 0, dailyStats: [] }
        this.widgetOrder = [...this.defaultOrder]
      }
    }
  },
  async mounted() {
    await this.loadData()
  }
})
</script>

<style scoped>
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 16px;
  margin-bottom: 20px;
  max-width: 100%;
  overflow-x: hidden;
}

.dashboard-widget {
  transition: all 0.3s ease;
  min-width: 0;
}

.widget-card {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.1);
  border: 2px solid var(--theme-dashboard-box, #2196F3);
  border-radius: 8px;
  min-height: 220px;
}

.widget-title {
  background: #f5f5f5;
  border-bottom: 2px solid var(--theme-dashboard-box, #2196F3);
  flex-shrink: 0;
}

.widget-content {
  flex: 1;
}

body.body--dark .widget-card {
  box-shadow: 0 1px 8px rgba(0, 0, 0, 0.5);
  border-color: #1976D2;
}

body.body--dark .widget-title {
  background: #1f1f1f;
  border-color: #1976D2;
}

.dashboard-widget:nth-child(6) {
  grid-column: 1 / -1;
}

@media (max-width: 1024px) {
  .dashboard-grid {
    grid-template-columns: repeat(6, 1fr);
  }

  .dashboard-widget:nth-child(6) {
    grid-column: 1 / -1;
  }
}

@media (max-width: 600px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .dashboard-widget:nth-child(6) {
    grid-column: 1 / -1;
  }
}

.full-height {
  height: 100%;
}

.chart-container {
  position: relative;
  width: 100%;
  height: 100%;
}

canvas {
  width: 100%;
  height: 100%;
}

.nested-box {
  border: 3px solid var(--theme-dashboard-nested-box, #2196F3) !important;
  border-radius: 8px;
  padding: 18px 20px;
  background: #ffffff;
  color: #000;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  min-height: 80px;
}

body.body--dark .nested-box {
  background: #2a2a2a;
  border-color: #1976D2 !important;
  color: #fff;
}

.strong-box {
  background: #eef3ff;
  border-color: #c5d2ff !important;
}

body.body--dark .strong-box {
  background: #1a2d5f;
  border-color: #3d5a99 !important;
}

.dashboard-page {
  min-height: 100vh;
  overflow-x: hidden;
}

.activity-row {
  border-bottom: 1px solid rgba(0,0,0,0.1);
}

body.body--dark .activity-row {
  border-bottom-color: rgba(255,255,255,0.1);
}

@keyframes pulse {
  0% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.15); opacity: 0.8; }
  100% { transform: scale(1); opacity: 1; }
}

.pulse-icon {
  animation: pulse 1.2s ease-in-out infinite;
}
</style>
