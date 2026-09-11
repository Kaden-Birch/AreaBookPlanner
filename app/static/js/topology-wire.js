import {api} from './api.js';
import {esc,openModal,toast} from './ui.js';

// A wire documents connectivity; it never configures hardware.
export function mountWireMode({body,canvas,byId,clinic,onStart,onSaved}) {
  let active=false,busy=false,source=null;
  const button=document.createElement('button');button.className='btn btn-sm';button.textContent='Connect physical wire';
  body.querySelector('#topology-assign-controls').prepend(button);
  const banner=document.createElement('div');banner.className='vlan-assignment-banner';banner.hidden=true;canvas.before(banner);
  const render=()=>{button.setAttribute('aria-pressed',String(active));banner.hidden=!active;banner.innerHTML=`<span>${source?'Now click the downstream device.':'Click the upstream device, then choose its port.'} Physical wires only; existing uplinks are kept.</span> <button class="btn btn-sm">Cancel wiring</button>`;banner.querySelector('button').onclick=stop;};
  function stop(){active=false;source=null;render();}
  button.onclick=()=>{if(active)stop();else{onStart();active=true;render();}};
  body.addEventListener('keydown',e=>{if(e.key==='Escape'&&!busy)stop();});
  async function choosePort(id){
    const data=await api.get(`/api/devices/${id}/network`);
    return new Promise(resolve=>{
      let result=null;
      const modal=openModal({title:`Choose port · ${byId.get(id)?.name||'Device'}`,body:`<label>Physical port<select>${'<option value="">Unknown port</option>'}${data.interfaces.filter(i=>i.connector!=='virtual').map(i=>{const occupied=data.connections.some(c=>(c.source_interface_id===i.id||c.target_interface_id===i.id)&&!['virtual','wireless'].includes(c.media));return `<option value="${i.id}" ${occupied?'disabled':''}>${esc(i.name)}${occupied?' — occupied':''}</option>`;}).join('')}</select></label><p class="help">Unknown port records the connection without reserving a specific socket.</p>`,footer:'<button class="btn" data-cancel>Cancel</button><button class="btn btn-primary" data-use>Use port</button>',onClose:()=>resolve(result)});
      modal.root.querySelector('[data-cancel]').onclick=()=>modal.close();
      modal.root.querySelector('[data-use]').onclick=()=>{result={id,port:Number(modal.body.querySelector('select').value)||null};modal.close();};
    });
  }
  async function click(id){
    if(busy)return;
    if(byId.get(id)?.device_type==='vm'){toast('VMs use virtual connections, not physical wires.','error');return;}
    if(source?.id===id){toast('Choose a different device.','error');return;}
    busy=true;
    try{
      const endpoint=await choosePort(id);if(!endpoint||!active)return;
      if(!source){source=endpoint;render();return;}
      await api.post(`/api/clinics/${clinic}/connections/attach`,{physical:true,parent:source.id,child:id,source_interface_id:source.port,target_interface_id:endpoint.port});
      stop();toast('Physical connection saved','success');onSaved?.();
    }catch(e){toast(e.message,'error');}finally{busy=false;}
  }
  for(const event of ['click','keydown'])canvas.addEventListener(event,e=>{if(!active||event==='keydown'&&!['Enter',' '].includes(e.key))return;const node=e.target.closest('[data-device]');if(!node)return;e.preventDefault();e.stopImmediatePropagation();click(Number(node.dataset.device));},true);
  return {get active(){return active;},stop};
}
