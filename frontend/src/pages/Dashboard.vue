<template>
  <q-page class="q-pa-sm dashboard-page">
    <div class="row items-center q-mb-md">
      <div class="col text-h4">Dashboard</div>
      <div class="col-auto q-gutter-sm">
        <q-banner v-if="isEditing" class="bg-info text-white q-mb-sm">
          <template v-slot:avatar>
            <q-icon name="info" />
          </template>
          Drag widgets to reorder • Drag right edge to resize width • Drag bottom edge to resize height
        </q-banner>
        <q-btn 
          v-if="isEditing" 
          color="positive" 
          label="Save Layout" 
          icon="save"
          @click="saveLayout"
          size="sm"
        />
        <q-btn 
          v-if="isEditing" 
          color="negative" 
          label="Cancel" 
          icon="close"
          @click="cancelEdit"
          size="sm"
        />
        <q-btn 
          v-if="!isEditing" 
          color="primary" 
          label="Edit Layout" 
          icon="edit"
          @click="startEdit"
          size="sm"
        />
        <q-btn 
          v-if="isAdmin && isEditing" 
          color="info" 
          label="Set as Default" 
          icon="check_circle"
          @click="setAsDefault"
          size="sm"
        />
        <q-btn 
          v-if="!isEditing" 
          flat 
          dense
          icon="more_vert"
        >
          <q-menu>
            <q-list style="min-width: 200px">
              <q-item clickable @click="resetLayout">
                <q-item-section>
                  <q-item-label>Reset to Default</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-menu>
        </q-btn>
      </div>
    </div>

    <div class="dashboard-grid">
      <div 
        v-for="(widget, index) in orderedWidgets" 
        :key="widget.id" 
        :class="getWidgetClass(widget)"
        :style="getWidgetStyle(widget)"
        :draggable="isEditing"
        @dragstart="onDragStart($event, index)"
        @dragover="onDragOver"
        @drop="onDrop($event, index)"
        @dragend="onDragEnd"
        @dragenter="onDragEnter($event, index)"
        @dragleave="onDragLeave"
      >
        <q-card class="full-height widget-card">
          <q-card-section class="q-py-sm widget-title">
            <div class="text-subtitle2 text-weight-bold">{{ widget.title }}</div>
            <q-icon v-if="isEditing" name="drag_handle" class="drag-handle" />
          </q-card-section>
          <q-separator />
          <q-card-section class="q-pa-sm widget-content">
            <component :is="widget.component" :stats="stats" />
          </q-card-section>
          <div 
            v-if="isEditing" 
            class="widget-resize-handle widget-resize-width"
            @mousedown="startResize($event, index, 'width')"
            title="Drag to resize width"
          ></div>
          <div 
            v-if="isEditing" 
            class="widget-resize-handle widget-resize-height"
            @mousedown="startResize($event, index, 'height')"
            title="Drag to resize height"
          ></div>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script>
import { defineComponent, h } from 'vue'
import { QList, QItem, QItemSection, QItemLabel } from 'quasar'
import api from '../services/api'

// Widget components - using render functions instead of templates
const ConfiguredDevicesWidget = defineComponent({
  props: ['stats'],
  computed: {
    totalDevices() {
      return Object.values(this.stats?.devicesByType || {}).reduce((a, b) => a + b, 0)
    }
  },
  render() {
    return h('div', { class: 'q-gutter-md q-pa-sm' }, [
      h('div', { class: 'row q-col-gutter-md' }, [
        h('div', { class: 'col-5' }, [
          h('div', { class: 'nested-box strong-box flex flex-center column', style: { minHeight: '100%' } }, [
            h('div', { class: 'text-subtitle2 text-weight-medium', style: { fontSize: '0.875rem', marginBottom: '8px' } }, 'Total'),
            h('div', { 
              class: 'text-primary text-weight-bold',
              style: { fontSize: 'clamp(2rem, 6vw, 4rem)', lineHeight: '1' }
            }, this.totalDevices.toString())
          ])
        ]),
        h('div', { class: 'col-7' }, [
          ...Object.entries(this.stats?.devicesByType || {}).map(([type, count]) =>
            h('div', { class: 'nested-box', key: type }, [
              h('div', { class: 'text-subtitle2 text-grey' }, type),
              h('div', { class: 'text-h5 text-weight-medium text-primary' }, count.toString())
            ])
          ),
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
    return h('div', { class: 'row q-col-gutter-md q-pa-sm' }, [
      h('div', { class: 'col-6' }, [
        h('div', { class: 'nested-box flex flex-center column', style: { minHeight: '100%' } }, [
          h('div', { class: 'text-subtitle2 text-weight-medium', style: { fontSize: '1rem', marginBottom: '8px' } }, 'Success'),
          h('div', { 
            class: 'text-positive text-weight-bold',
            style: { fontSize: 'clamp(2rem, 6vw, 4rem)', lineHeight: '1' }
          }, (this.stats?.success24h || 0).toString())
        ])
      ]),
      h('div', { class: 'col-6' }, [
        h('div', { class: 'nested-box flex flex-center column', style: { minHeight: '100%' } }, [
          h('div', { class: 'text-subtitle2 text-weight-medium', style: { fontSize: '1rem', marginBottom: '8px' } }, 'Failed'),
          h('div', { 
            class: 'text-negative text-weight-bold',
            style: { fontSize: 'clamp(2rem, 6vw, 4rem)', lineHeight: '1' }
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
        style: { fontSize: 'clamp(2rem, 8vw, 5rem)', lineHeight: '1.2' }
      }, (this.stats?.avgDuration || 0) + 's')
    ])
  }
})

const SuccessRateWidget = defineComponent({
  props: ['stats'],
  computed: {
    rate() {
      const total = (this.stats?.success24h || 0) + (this.stats?.failed24h || 0)
      return total > 0 ? Math.round((this.stats.success24h / total) * 100) : 0
    }
  },
  render() {
    return h('div', { 
      class: 'full-height flex flex-center',
      style: { padding: '20px' }
    }, [
      h('div', { 
        class: 'text-positive text-weight-bold dynamic-text',
        style: { fontSize: 'clamp(2rem, 8vw, 5rem)', lineHeight: '1.2' }
      }, this.rate + '%')
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
      const padding = 40
      const chartWidth = width - padding * 2
      const chartHeight = height - padding * 2
      const barWidth = chartWidth / dailyStats.length
      const textColor = this.isDarkMode() ? '#fff' : '#000'
      dailyStats.forEach((day, index) => {
        const x = padding + index * barWidth
        const barH = (day.rate / 100) * chartHeight
        const y = height - padding - barH
        ctx.fillStyle = day.rate >= 80 ? '#21BA45' : day.rate >= 50 ? '#F2C037' : '#C10015'
        ctx.fillRect(x + 5, y, barWidth - 10, barH)
        ctx.fillStyle = textColor
        ctx.font = '10px sans-serif'
        ctx.textAlign = 'center'
        const label = new Date(day.date).toLocaleDateString('en-US', { weekday: 'short' })
        ctx.fillText(label, x + barWidth / 2, height - padding + 20)
        ctx.fillText(`${Math.round(day.rate)}%`, x + barWidth / 2, y - 5)
      })
      ctx.strokeStyle = this.isDarkMode() ? '#555' : '#ccc'
      ctx.beginPath()
      ctx.moveTo(padding, height - padding)
      ctx.lineTo(width - padding, height - padding)
      ctx.moveTo(padding, padding)
      ctx.lineTo(padding, height - padding)
      ctx.stroke()
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
    return { recentActivity: [] }
  },
  mounted() {
    this.loadActivity()
  },
  methods: {
    async loadActivity() {
      try {
        const res = await api.get('/audit-logs/?limit=10')
        this.recentActivity = Array.isArray(res.data) ? res.data : res.data.results || []
      } catch (e) {
        this.recentActivity = []
      }
    },
    formatDate(dateStr) {
      if (!dateStr) return ''
      return new Date(dateStr).toLocaleString()
    }
  },
  render() {
    return h(QList, { separator: true, style: 'max-height: 300px; overflow-y: auto' }, () => [
      this.recentActivity.length > 0
        ? this.recentActivity.map(item =>
            h(QItem, { key: item.id }, () => [
              h(QItemSection, () => [
                h(QItemLabel, { class: 'text-caption' }, () => item.action),
                h(QItemLabel, { caption: true }, () => this.formatDate(item.created_at))
              ])
            ])
          )
        : h(QItem, () => [
            h(QItemSection, () => [
              h(QItemLabel, { caption: true }, () => 'No recent activity')
            ])
          ])
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
    return {
      stats: { devicesByType: {}, success24h: 0, failed24h: 0, avgDuration: 0, dailyStats: [] },
      isEditing: false,
      isAdmin: false,
      widgetOrder: [
        { id: 'devices', width: 3, height: 220 },
        { id: 'backups', width: 3, height: 220 },
        { id: 'avgtime', width: 3, height: 220 },
        { id: 'successrate', width: 3, height: 440 },
        { id: 'chart', width: 12, height: 300 },
        { id: 'activity', width: 12, height: 300 }
      ],
      defaultOrder: [
        { id: 'devices', width: 3, height: 220 },
        { id: 'backups', width: 3, height: 220 },
        { id: 'avgtime', width: 3, height: 220 },
        { id: 'successrate', width: 3, height: 440 },
        { id: 'chart', width: 12, height: 300 },
        { id: 'activity', width: 12, height: 300 }
      ],
      draggedIndex: null,
      dragOverIndex: null,
      resizingIndex: null
    }
  },
  computed: {
    orderedWidgets() {
      const widgetMap = {
        devices: { id: 'devices', title: 'Configured Devices', component: ConfiguredDevicesWidget },
        backups: { id: 'backups', title: 'Backups (24h)', component: BackupsWidget },
        avgtime: { id: 'avgtime', title: 'Avg Backup Time', component: AvgTimeWidget },
        successrate: { id: 'successrate', title: 'Success Rate', component: SuccessRateWidget },
        chart: { id: 'chart', title: 'Backup Success Rate (Last 7 Days)', component: ChartWidget },
        activity: { id: 'activity', title: 'Recent Activity', component: ActivityWidget }
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
    getWidgetClass(widget) {
      const baseClass = 'dashboard-widget'
      let classes = [baseClass]
      if (this.isEditing) classes.push('editing')
      if (this.draggedIndex !== null && this.orderedWidgets[this.draggedIndex]?.id === widget.id) {
        classes.push('dragging')
      }
      return classes.join(' ')
    },
    getWidgetStyle(widget) {
      return {
        gridColumn: `span ${widget.width}`,
        minHeight: `${widget.height || 220}px`
      }
    },
    startResize(e, index, dimension) {
      e.preventDefault()
      this.resizingIndex = index
      const startX = e.clientX
      const startY = e.clientY
      const startWidth = this.widgetOrder[index].width
      const startHeight = this.widgetOrder[index].height || 220
      
      const handleMouseMove = (moveEvent) => {
        if (dimension === 'width') {
          const delta = moveEvent.clientX - startX
          const pixelsPerColumn = 100 / 12
          const columnDelta = Math.round(delta / (window.innerWidth * pixelsPerColumn / 100))
          let newWidth = Math.max(2, Math.min(12, startWidth + columnDelta))
          this.widgetOrder[index].width = newWidth
        } else if (dimension === 'height') {
          const delta = moveEvent.clientY - startY
          let newHeight = Math.max(150, startHeight + delta)
          this.widgetOrder[index].height = newHeight
        }
      }
      
      const handleMouseUp = () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
        this.resizingIndex = null
      }
      
      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
    },
    async loadData() {
      try {
        const [statsRes, layoutRes] = await Promise.all([
          api.get('/dashboard-stats/'),
          api.get('/dashboard-layout/')
        ])
        this.stats = statsRes.data
        // Check if layout exists AND has items
        const layoutData = layoutRes.data?.layout || layoutRes.data
        if (layoutData && Array.isArray(layoutData) && layoutData.length > 0) {
          this.widgetOrder = layoutData.map(item => {
            const normalized = typeof item === 'string' ? { id: item } : { ...item }
            // Apply defaults for width/height if missing
            if (!normalized.width) {
              normalized.width = normalized.id === 'chart' || normalized.id === 'activity' ? 12 : 3
            }
            if (!normalized.height) {
              normalized.height = normalized.id === 'successrate'
                ? 440
                : normalized.id === 'chart' || normalized.id === 'activity'
                ? 300
                : 220
            }
            return normalized
          })
        } else {
          this.widgetOrder = [...this.defaultOrder]
        }
      } catch (e) {
        console.error('Failed to load dashboard:', e)
        this.widgetOrder = [...this.defaultOrder]
      }
    },
    startEdit() {
      this.isEditing = true
    },
    cancelEdit() {
      this.isEditing = false
      this.loadData()
    },
    async saveLayout() {
      try {
        await api.post('/dashboard-layout/', { layout: this.widgetOrder })
        this.$q.notify({ type: 'positive', message: 'Layout saved', position: 'top' })
        this.isEditing = false
      } catch (e) {
        this.$q.notify({ type: 'negative', message: 'Failed to save layout', position: 'top' })
      }
    },
    async setAsDefault() {
      try {
        await api.post('/dashboard-layout/default/', { layout: this.widgetOrder })
        this.$q.notify({ type: 'positive', message: 'Set as default for all new users', position: 'top' })
      } catch (e) {
        this.$q.notify({ type: 'negative', message: 'Failed to set default', position: 'top' })
      }
    },
    async resetLayout() {
      this.widgetOrder = [...this.defaultOrder]
      try {
        await api.post('/dashboard-layout/', { layout: this.defaultOrder })
        this.$q.notify({ type: 'info', message: 'Layout reset to default', position: 'top' })
      } catch (e) {
        this.$q.notify({ type: 'negative', message: 'Failed to reset layout', position: 'top' })
      }
    },
    onDragStart(e, index) {
      this.draggedIndex = index
      e.dataTransfer.effectAllowed = 'move'
      e.dataTransfer.setData('text/html', e.currentTarget)
    },
    onDragOver(e) {
      if (!this.isEditing) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
    },
    onDragEnter(e, index) {
      if (!this.isEditing) return
      this.dragOverIndex = index
      e.currentTarget.classList.add('drag-over')
    },
    onDragLeave(e) {
      if (!this.isEditing) return
      e.currentTarget.classList.remove('drag-over')
      if (e.currentTarget.contains(e.relatedTarget)) return
      this.dragOverIndex = null
    },
    onDrop(e, dropIndex) {
      if (!this.isEditing) return
      e.preventDefault()
      e.currentTarget.classList.remove('drag-over')
      
      if (this.draggedIndex !== null && this.draggedIndex !== dropIndex) {
        const widgets = [...this.widgetOrder]
        const draggedWidget = widgets[this.draggedIndex]
        widgets.splice(this.draggedIndex, 1)
        
        const actualDropIndex = this.draggedIndex < dropIndex ? dropIndex - 1 : dropIndex
        widgets.splice(actualDropIndex, 0, draggedWidget)
        
        this.widgetOrder = widgets
      }
      this.draggedIndex = null
      this.dragOverIndex = null
    },
    onDragEnd(e) {
      e.currentTarget.classList.remove('drag-over')
      this.draggedIndex = null
      this.dragOverIndex = null
    }
  },
  async mounted() {
    const user = localStorage.getItem('user')
    this.isAdmin = user ? JSON.parse(user).is_staff : false
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

.dashboard-widget.editing {
  cursor: grab;
  opacity: 0.9;
}

.dashboard-widget.editing:active {
  cursor: grabbing;
}

.dashboard-widget.dragging {
  opacity: 0.5;
  transform: scale(0.98);
}

.dashboard-widget.drag-over {
  background-color: #e3f2fd;
  border-radius: 8px;
  box-shadow: inset 0 0 0 2px #2196F3;
}

.drag-handle {
  float: right;
  cursor: grab;
  opacity: 0.7;
  margin-left: 8px;
}

.drag-handle:active {
  cursor: grabbing;
}

.widget-resize-handle {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  background: linear-gradient(to right, transparent, #2196F3);
  opacity: 0;
  transition: opacity 0.2s ease;
}

.widget-resize-handle.widget-resize-width {
  right: 0;
  cursor: col-resize;
}

.widget-resize-handle.widget-resize-height {
  right: auto;
  left: 0;
  top: auto;
  bottom: 0;
  width: 100%;
  height: 6px;
  background: linear-gradient(to bottom, transparent, #2196F3);
  cursor: row-resize;
}

.dashboard-widget.editing:hover .widget-resize-handle {
  opacity: 0.8;
}

.widget-resize-handle:hover {
  opacity: 1 !important;
  background: linear-gradient(to right, transparent, #1976D2);
}

.widget-resize-height:hover {
  background: linear-gradient(to bottom, transparent, #1976D2) !important;
}

.widget-card {
  position: relative;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 5px rgba(0, 0, 0, 0.1);
  border: 2px solid #2196F3;
  border-radius: 8px;
  min-height: 220px;
}

body.body--dark .widget-card {
  box-shadow: 0 1px 8px rgba(0, 0, 0, 0.5);
  border-color: #1976D2;
}

.dashboard-widget:nth-child(5) {
  grid-column: 1 / -1;
}

.dashboard-widget:nth-child(6) {
  grid-column: 1 / -1;
}

@media (max-width: 1024px) {
  .dashboard-grid {
    grid-template-columns: repeat(6, 1fr);
  }
  
  .dashboard-widget:nth-child(5),
  .dashboard-widget:nth-child(6) {
    grid-column: 1 / -1;
  }
}

@media (max-width: 600px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }
  
  .dashboard-widget:nth-child(5),
  .dashboard-widget:nth-child(6) {
    grid-column: 1;
  }
}



.widget-title {
  background: #f5f5f5;
  border-bottom: 2px solid #2196F3;
  flex-shrink: 0;
  color: #000;
  font-weight: 600;
}

body.body--dark .widget-title {
  background: #1e1e1e;
  border-bottom-color: #1976D2;
  color: #fff;
}

.widget-content {
  flex: 1;
  overflow: auto;
  color: #000;
}

body.body--dark .widget-content {
  color: #fff;
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
  border: 2px solid #2196F3 !important;
  border-radius: 8px;
  padding: 18px 20px;
  background: #fafafa;
  color: #000;
}

body.body--dark .nested-box {
  background: #1e1e1e;
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
</style>
