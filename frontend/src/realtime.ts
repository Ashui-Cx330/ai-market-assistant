import { reactive, ref } from "vue";

export type RealtimeEvent = { type:string; key?:string; data:any; serverTimestamp?:string };

class RealtimeMarketStore {
  states = reactive<Record<string, any>>({});
  connectionStatus = ref("CONNECTING");
  lastUpdateTime = ref("");
  latencyMs = ref<number|null>(null);
  serverOffsetMs = ref(0);
  private socket: WebSocket|null = null;
  private reconnectSeconds = 1;
  private reconnectTimer: number|null = null;
  private heartbeatTimer: number|null = null;
  private staleTimer: number|null = null;
  private wanted = new Map<string,{asset_type:string;symbol:string;interval:string}>();
  private listeners = new Set<(event:RealtimeEvent)=>void>();
  private deliberatelyClosed = false;

  key(assetType:string,symbol:string,interval:string){return `${assetType}:${symbol.toUpperCase()}:${interval}`}

  connect(){
    if(this.socket && (this.socket.readyState===WebSocket.OPEN||this.socket.readyState===WebSocket.CONNECTING)) return;
    this.deliberatelyClosed=false; this.connectionStatus.value="CONNECTING";
    const protocol=location.protocol==="https:"?"wss":"ws";
    this.socket=new WebSocket(`${protocol}://${location.host}/api/realtime/ws`);
    this.socket.onopen=()=>{
      this.connectionStatus.value="CONNECTED";this.reconnectSeconds=1;
      for(const request of this.wanted.values()) this.send({action:"subscribe",...request});
    };
    this.socket.onmessage=(message)=>this.receive(JSON.parse(message.data) as RealtimeEvent);
    this.socket.onerror=()=>{this.connectionStatus.value="WARNING"};
    this.socket.onclose=()=>{
      this.connectionStatus.value="DISCONNECTED";
      if(!this.deliberatelyClosed){
        if(this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer=window.setTimeout(()=>this.connect(),this.reconnectSeconds*1000);
        this.reconnectSeconds=Math.min(this.reconnectSeconds*2,30);
      }
    };
    if(!this.heartbeatTimer) this.heartbeatTimer=window.setInterval(()=>this.send({action:"ping"}),15000);
    if(!this.staleTimer) this.staleTimer=window.setInterval(()=>this.checkStale(),2000);
  }

  subscribe(asset_type:string,symbol:string,interval:string){
    const request={asset_type,symbol,interval};this.wanted.set(this.key(asset_type,symbol,interval),request);
    this.connect();this.send({action:"subscribe",...request});
  }

  onEvent(listener:(event:RealtimeEvent)=>void){this.listeners.add(listener);return()=>this.listeners.delete(listener)}

  close(){
    this.deliberatelyClosed=true;if(this.reconnectTimer)window.clearTimeout(this.reconnectTimer);
    if(this.heartbeatTimer)window.clearInterval(this.heartbeatTimer);
    if(this.staleTimer)window.clearInterval(this.staleTimer);
    this.socket?.close();this.socket=null;this.heartbeatTimer=null;this.staleTimer=null;
  }

  private send(payload:any){if(this.socket?.readyState===WebSocket.OPEN)this.socket.send(JSON.stringify(payload))}

  private receive(event:RealtimeEvent){
    const received=Date.now();
    const serverStamp=event.serverTimestamp||event.data?.serverTimestamp;
    if(serverStamp){const server=Date.parse(serverStamp);if(Number.isFinite(server))this.serverOffsetMs.value=server-received}
    if(event.key){
      if(event.type==="snapshot"||event.type==="ticker") this.states[event.key]=event.data;
      else if(event.type==="candle") this.states[event.key]=event.data.state;
      else if(event.type==="connection")this.states[event.key]={...(this.states[event.key]||{}),connectionStatus:event.data.status,connectionReason:event.data.reason};
      else this.states[event.key]={...(this.states[event.key]||{}),[event.type]:event.data};
    }
    if(event.type==="connection"&&!event.key)this.connectionStatus.value=event.data.status;
    else if(["ticker","candle","analysis"].includes(event.type)){
      this.connectionStatus.value="CONNECTED";this.lastUpdateTime.value=new Date(received).toLocaleTimeString("zh-CN");
      const data=event.type==="candle"?event.data.state:event.data;
      this.latencyMs.value=data?.latencyMs??this.latencyMs.value;
    }
    for(const listener of this.listeners)listener(event);
  }

  private checkStale(){
    const recent=Object.values(this.states).reduce((value:any,item:any)=>Math.max(value,Number(item?.lastUpdateTime||0)),0);
    if(!recent)return;
    const age=(Date.now()/1000)-recent;
    if(age>60)this.connectionStatus.value="DISCONNECTED";
    else if(age>30)this.connectionStatus.value="STALE";
    else if(age>10)this.connectionStatus.value="WARNING";
  }
}

export const realtimeMarketStore=new RealtimeMarketStore();
