// CSV text is quoted and neutralized for spreadsheet formula injection.
export const csvCell=value=>{
  let text=String(value??'');
  if(/^[\s]*[=+@-]/.test(text)||/^[\t\r\n]/.test(text))text="'"+text;
  return '"'+text.replaceAll('"','""')+'"';
};

export function viewData(graph,context) {
  const ids=new Set(graph.nodes.map(n=>n.id));
  return {...context,nodes:graph.nodes.map(n=>({...n,children:(n.children||[]).filter(id=>ids.has(id))})),
    edges:graph.edges.map(({hidden,...edge})=>({...edge,hidden_count:hidden.length}))};
}
