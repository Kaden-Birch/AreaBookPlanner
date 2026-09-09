export function displayedVpns(links,show,onlyUp) {
  return show?links.filter(link=>!onlyUp||link.status==='up'):[];
}
export function vpnDisplayClass(status) {
  return ['up','down','disabled'].includes(status)?`vpn-recorded-${status}`:'vpn-recorded-unknown';
}
