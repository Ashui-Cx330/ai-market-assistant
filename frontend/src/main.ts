import { createApp } from 'vue'
import { ElDialog } from 'element-plus'
import 'element-plus/es/components/base/style/css'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/message/style/css'
import './style.css'
import './intelligence.css'
import App from './App.vue'
createApp(App).component('ElDialog', ElDialog).mount('#app')
