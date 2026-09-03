<script setup lang="ts">
import * as echarts from 'echarts';import { nextTick,onBeforeUnmount,onMounted,ref,watch } from 'vue'
const props=defineProps<{curve:Array<{timestamp:string;equity:number}>}>();const root=ref<HTMLDivElement>();let chart:echarts.ECharts|null=null
function render(){if(!root.value||!props.curve.length)return;chart??=echarts.init(root.value);chart.setOption({grid:{left:58,right:18,top:18,bottom:38},tooltip:{trigger:'axis'},xAxis:{type:'category',data:props.curve.map(x=>x.timestamp.slice(0,10)),axisLabel:{color:'#637991'},axisLine:{lineStyle:{color:'#31465d'}}},yAxis:{type:'value',scale:true,axisLabel:{color:'#637991'},splitLine:{lineStyle:{color:'#17283a'}}},dataZoom:[{type:'inside'},{type:'slider',height:16,bottom:3}],series:[{type:'line',data:props.curve.map(x=>x.equity),showSymbol:false,smooth:true,lineStyle:{color:'#28d3a4',width:2},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'#28d3a455'},{offset:1,color:'#28d3a400'}]}}}]},true)}
const resize=()=>chart?.resize();onMounted(()=>{nextTick(render);window.addEventListener('resize',resize)});watch(()=>props.curve,()=>nextTick(render),{deep:true});onBeforeUnmount(()=>{window.removeEventListener('resize',resize);chart?.dispose()})
</script><template><div ref="root" class="equity-chart"></div></template>

