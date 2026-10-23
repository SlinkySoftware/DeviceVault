// SPDX-License-Identifier: GPL-3.0-or-later
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  { ignores: ['dist/**', '.quasar/**', 'node_modules/**', 'public/**'] },
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  {
    rules: {
      // The codebase standard: TypeScript and <script setup> everywhere.
      'vue/block-lang': ['error', { script: { lang: 'ts' } }],
      'vue/component-api-style': ['error', ['script-setup']],
      'vue/define-macros-order': ['error', { order: ['defineProps', 'defineModel', 'defineEmits'] }],
      // Text is never rendered as HTML (backup contents are untrusted).
      'vue/no-v-html': 'error',
      'vue/no-unused-refs': 'error',
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
)
