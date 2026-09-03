export type AssetType = 'stock' | 'crypto'
export type Asset = {symbol:string; name:string; asset_type:AssetType; pair?:string; source?:string; available?:boolean; price?:number|null; change_percent?:number|null; currency?:string}
export type Quote = Asset & {price:number; change:number; change_percent:number; currency:string; open:number; previous_close:number|null; high:number; low:number; volume:number; amount:number|null; updated_at:string}
export type Candle = {timestamp:string;open:number;high:number;low:number;close:number;volume:number;amount:number}
export type IndicatorSet = {latest:Record<string,number|null>;series:Array<Record<string,number|string|null>>;score:number}

export async function request<T>(url:string, options?:RequestInit):Promise<T>{
  const response=await fetch(url,options)
  let body:any
  try{body=await response.json()}catch{throw new Error(`服务返回无效数据（HTTP ${response.status}）`)}
  if(!response.ok||body.success===false)throw new Error(body.message||`请求失败（HTTP ${response.status}）`)
  return (body.data??body) as T
}

export const post=<T>(url:string,data:unknown)=>request<T>(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
export const assetLabel=(asset:Asset)=>asset.asset_type==='crypto'?`${asset.symbol}/USDT`:asset.name

