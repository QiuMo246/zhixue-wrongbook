import { createApp } from 'vue'
// MiSans Heavy：按 unicode-range 分块的自托管中文字体，标题专用；
// 浏览器只下载页面实际用到的字块
import 'misans/lib/Normal/MiSans-Heavy.min.css'
import './style.css'
import App from './App.vue'

createApp(App).mount('#app')
