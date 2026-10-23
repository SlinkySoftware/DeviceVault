<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- Standard page frame: title, caption and actions above a card body. -->
<template>
  <q-page padding>
    <q-card>
      <q-card-section>
        <div class="row items-center q-col-gutter-sm">
          <div class="col">
            <div class="text-h5">{{ title }}</div>
            <div v-if="caption || $slots.caption" class="text-caption text-grey">
              <slot name="caption">{{ caption }}</slot>
            </div>
          </div>
          <div v-if="$slots.actions" class="col-auto row q-gutter-sm">
            <slot name="actions" />
          </div>
        </div>
      </q-card-section>
      <q-separator />
      <q-card-section>
        <slot />
      </q-card-section>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
defineProps<{ title: string; caption?: string }>()
</script>
