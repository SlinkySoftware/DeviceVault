<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<template>
  <PageCard title="Theme" caption="Application colours, applied for every user">
    <q-form class="q-gutter-md" @submit="save">
      <div class="row q-col-gutter-md">
        <div v-for="field in FIELDS" :key="field.key" class="col-12 col-md-4">
          <q-input v-model="form[field.key]" :label="field.label" outlined :rules="[hexColor]">
            <template #prepend>
              <div class="swatch" :style="{ backgroundColor: form[field.key] }" />
            </template>
            <template #append>
              <q-icon name="palette" class="cursor-pointer" :aria-label="`Pick ${field.label}`">
                <q-popup-proxy cover transition-show="scale" transition-hide="scale">
                  <q-color v-model="form[field.key]" no-header-tabs format-model="hex" />
                </q-popup-proxy>
              </q-icon>
            </template>
          </q-input>
        </div>
      </div>
      <div class="row q-gutter-sm">
        <q-btn type="submit" color="primary" icon="save" label="Save" :loading="saving" />
        <q-btn flat color="primary" icon="restart_alt" label="Reset to defaults" @click="resetDefaults" />
      </div>
    </q-form>

    <div class="text-h6 q-mt-lg q-mb-sm">Preview</div>
    <div class="preview">
      <div class="preview__bar text-white q-pa-sm" :style="{ backgroundColor: form.title_bar_color }">
        Application title bar
      </div>
      <div class="q-pa-md">
        <div class="preview__card q-pa-md" :style="{ borderColor: form.dashboard_box_color }">
          <div class="text-weight-bold q-mb-sm">Card border</div>
          <div class="preview__nested q-pa-sm" :style="{ borderColor: form.dashboard_nested_box_color }">Nested box</div>
        </div>
      </div>
    </div>
  </PageCard>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'

import type { ThemeColors } from '@/api/types'
import PageCard from '@/components/PageCard.vue'
import { useNotify } from '@/composables/useNotify'
import { DEFAULT_COLORS, useThemeStore } from '@/stores/theme'
import { hexColor } from '@/utils/rules'

const FIELDS: { key: keyof ThemeColors; label: string }[] = [
  { key: 'title_bar_color', label: 'Title bar' },
  { key: 'dashboard_box_color', label: 'Card border' },
  { key: 'dashboard_nested_box_color', label: 'Nested box border' },
]

const theme = useThemeStore()
const notify = useNotify()
const form = reactive<ThemeColors>({ ...theme.colors })
const saving = ref(false)

function resetDefaults(): void {
  Object.assign(form, DEFAULT_COLORS)
}

async function save(): Promise<void> {
  saving.value = true
  try {
    await theme.saveColors({ ...form })
    notify.success('Theme saved')
  } catch (error) {
    notify.error(error, 'Failed to save theme')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.swatch {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: 1px solid rgba(128, 128, 128, 0.5);
}

.preview {
  border: 1px solid rgba(128, 128, 128, 0.3);
  border-radius: 8px;
  overflow: hidden;
}

.preview__card {
  border: 2px solid;
  border-radius: 8px;
}

.preview__nested {
  border: 3px solid;
  border-radius: 4px;
}
</style>
