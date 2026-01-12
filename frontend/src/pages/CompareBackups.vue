<template>
  <q-page class="q-pa-md">
    <q-card>
      <q-card-section>
        <div class="row items-center">
          <div class="col">
            <div class="text-h4">Compare Backups</div>
            <div class="text-caption text-grey">Side-by-side comparison of device configurations</div>
          </div>
          <div class="col-auto">
            <q-btn
              color="primary"
              label="Back to Backups"
              icon="arrow_back"
              @click="goBack"
            />
          </div>
        </div>
      </q-card-section>
      
      <q-separator />
      
      <q-card-section v-if="loadingBackups" class="text-center q-py-lg">
        <q-spinner color="primary" size="50px" />
        <div class="text-grey q-mt-md">Loading backups...</div>
      </q-card-section>

      <q-card-section v-else-if="backupA && backupB">
        <div class="row q-col-gutter-md">
          <div class="col-12 col-md-6">
            <div class="header-a q-pa-md rounded-borders q-mb-md">
              <div class="text-subtitle2 text-weight-bold text-white">Backup A</div>
              <div class="text-caption text-white">{{ formatDateTime(backupA.timestamp) }}</div>
            </div>
            <div ref="leftPane" class="backup-content q-pa-none rounded-borders" @scroll="onLeftScroll">
              <div v-for="(row, idx) in diffRows" :key="'l-'+idx" :class="['diff-line', rowClassLeft(row)]" v-html="renderLeft(row)"></div>
            </div>
          </div>
          <div class="col-12 col-md-6">
            <div class="header-b q-pa-md rounded-borders q-mb-md">
              <div class="text-subtitle2 text-weight-bold text-white">Backup B</div>
              <div class="text-caption text-white">{{ formatDateTime(backupB.timestamp) }}</div>
            </div>
            <div ref="rightPane" class="backup-content q-pa-none rounded-borders" @scroll="onRightScroll">
              <div v-for="(row, idx) in diffRows" :key="'r-'+idx" :class="['diff-line', rowClassRight(row)]" v-html="renderRight(row)"></div>
            </div>
          </div>
        </div>
      </q-card-section>

      <q-card-section v-else class="text-center q-py-lg">
        <div class="text-negative">Failed to load backups for comparison</div>
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useQuasar } from 'quasar'
import api from '../services/api'

const router = useRouter()
const route = useRoute()
const $q = useQuasar()

// State
const backupA = ref(null)
const backupB = ref(null)
const contentA = ref('')
const contentB = ref('')
const loadingBackups = ref(false)
const diffRows = ref([])
const leftPane = ref(null)
const rightPane = ref(null)
let _syncing = false

// Utility
function formatDateTime(isoString) {
  const date = new Date(isoString)
  return date.toLocaleString()
}

function goBack() {
  router.back()
}

function computeDiff() {
  const aLines = (contentA.value || '').split('\n')
  const bLines = (contentB.value || '').split('\n')
  const n = aLines.length
  const m = bLines.length
  const dp = Array(n + 1).fill(null).map(() => Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (aLines[i] === bLines[j]) dp[i][j] = dp[i + 1][j + 1] + 1
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  // build ops
  const ops = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (aLines[i] === bLines[j]) {
      ops.push({ type: 'equal', a: aLines[i], b: bLines[j] })
      i++; j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ type: 'delete', a: aLines[i] })
      i++
    } else {
      ops.push({ type: 'insert', b: bLines[j] })
      j++
    }
  }
  while (i < n) { ops.push({ type: 'delete', a: aLines[i++] }) }
  while (j < m) { ops.push({ type: 'insert', b: bLines[j++] }) }

  // coalesce deletes/inserts into replaces (modified)
  const rows = []
  let delBuf = []
  let insBuf = []
  const flushBuffers = () => {
    const k = Math.min(delBuf.length, insBuf.length)
    for (let t = 0; t < k; t++) {
      rows.push({ left: delBuf[t], right: insBuf[t], kind: 'modified' })
    }
    for (let t = k; t < delBuf.length; t++) {
      rows.push({ left: delBuf[t], right: '', kind: 'removed' })
    }
    for (let t = k; t < insBuf.length; t++) {
      rows.push({ left: '', right: insBuf[t], kind: 'added' })
    }
    delBuf = []
    insBuf = []
  }

  for (const op of ops) {
    if (op.type === 'equal') {
      flushBuffers()
      rows.push({ left: op.a, right: op.b, kind: 'equal' })
    } else if (op.type === 'delete') {
      delBuf.push(op.a)
    } else if (op.type === 'insert') {
      insBuf.push(op.b)
    }
  }
  flushBuffers()

  diffRows.value = rows
  // Precompute HTML for rendering
  for (const r of diffRows.value) {
    r.leftHtml = escapeHtml(r.left || '')
    r.rightHtml = escapeHtml(r.right || '')
  }
}

function rowClassLeft(row) {
  if (row.kind === 'removed') return 'removed'
  if (row.kind === 'modified') return 'modified'
  return ''
}

function rowClassRight(row) {
  if (row.kind === 'added') return 'added'
  if (row.kind === 'modified') return 'modified'
  return ''
}

function onLeftScroll() {
  if (_syncing) return
  _syncing = true
  if (rightPane.value) rightPane.value.scrollTop = leftPane.value.scrollTop
  requestAnimationFrame(() => { _syncing = false })
}

function onRightScroll() {
  if (_syncing) return
  _syncing = true
  if (leftPane.value) leftPane.value.scrollTop = rightPane.value.scrollTop
  requestAnimationFrame(() => { _syncing = false })
}

function escapeHtml(s) {
  return (s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function intralineDiff(a, b) {
  const s1 = a || ''
  const s2 = b || ''
  const n = s1.length, m = s2.length
  const dp = Array(n + 1).fill(null).map(() => Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (s1[i] === s2[j]) dp[i][j] = dp[i + 1][j + 1] + 1
      else dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  let i = 0, j = 0
  const leftSegs = []
  const rightSegs = []
  while (i < n && j < m) {
    if (s1[i] === s2[j]) {
      leftSegs.push({ t: 'eq', v: s1[i] })
      rightSegs.push({ t: 'eq', v: s2[j] })
      i++; j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      leftSegs.push({ t: 'chg', v: s1[i++] })
    } else {
      rightSegs.push({ t: 'chg', v: s2[j++] })
    }
  }
  while (i < n) leftSegs.push({ t: 'chg', v: s1[i++] })
  while (j < m) rightSegs.push({ t: 'chg', v: s2[j++] })

  const renderSegs = (segs) => segs.map(seg => seg.t === 'eq' ? escapeHtml(seg.v) : `<span style="background: #ffeb3b; color: #333; font-weight: 700; padding: 0 2px;">${escapeHtml(seg.v)}</span>`).join('')
  return {
    left: renderSegs(leftSegs),
    right: renderSegs(rightSegs)
  }
}

function renderLeft(row) {
  return row.leftHtml != null ? row.leftHtml : escapeHtml(row.left || '')
}

function renderRight(row) {
  return row.rightHtml != null ? row.rightHtml : escapeHtml(row.right || '')
}

// Load backup details and content
async function loadBackup(backupId) {
  try {
    const response = await api.get(`/stored-backups/${backupId}/`)
    return response.data
  } catch (error) {
    $q.notify({ type: 'negative', message: `Failed to fetch backup ${backupId}` })
    return null
  }
}

// Load backup content
async function loadBackupContent(backupId) {
  try {
    const response = await api.get(`/stored-backups/${backupId}/download/`, {
      responseType: 'text'
    })
    return response.data || '(empty backup)'
  } catch (error) {
    return `Error loading backup: ${error.response?.data?.error || error.message}`
  }
}

// Load both backups
async function loadBackups() {
  loadingBackups.value = true
  try {
    const backupAId = route.query.backup_a
    const backupBId = route.query.backup_b

    if (!backupAId || !backupBId) {
      $q.notify({ type: 'negative', message: 'Invalid backup IDs' })
      return
    }

    // Load backup metadata and content in parallel
    const [metaA, metaB, contentAData, contentBData] = await Promise.all([
      loadBackup(backupAId),
      loadBackup(backupBId),
      loadBackupContent(backupAId),
      loadBackupContent(backupBId)
    ])

    // Ensure older backup is A (left) and newer is B (right)
    if (metaA && metaB) {
      const dateA = new Date(metaA.timestamp)
      const dateB = new Date(metaB.timestamp)
      if (dateA > dateB) {
        // Swap: A is newer, so swap to make B the newer one
        backupA.value = metaB
        backupB.value = metaA
        contentA.value = contentBData
        contentB.value = contentAData
      } else {
        backupA.value = metaA
        backupB.value = metaB
        contentA.value = contentAData
        contentB.value = contentBData
      }
    } else if (metaA) {
      backupA.value = metaA
      contentA.value = contentAData
    } else if (metaB) {
      backupB.value = metaB
      contentB.value = contentBData
    }
    computeDiff()
  } finally {
    loadingBackups.value = false
  }
}

// Lifecycle
onMounted(() => {
  loadBackups()
})

watch([contentA, contentB], () => computeDiff())
onBeforeUnmount(() => {
  // listeners are attached inline on elements; nothing to clean up
})
</script>

<style scoped>
.backup-content {
  overflow: auto;
  max-height: 65vh;
  font-family: monospace;
  white-space: pre;
  font-size: 11px;
  line-height: 1.4;
  background: #1e1e1e;
  color: #e0e0e0;
  border: 1px solid #2d2d2d;
}

.header-a {
  background: #12314f;
}

.header-b {
  background: #1f4a2e;
}

.diff-line {
  padding: 2px 8px;
  min-height: 1.7em;
}
.diff-line.added { background: rgba(46, 160, 67, 0.25); }
.diff-line.removed { background: rgba(248, 81, 73, 0.25); }
.diff-line.modified { background: rgba(187, 128, 9, 0.25); }
</style>
