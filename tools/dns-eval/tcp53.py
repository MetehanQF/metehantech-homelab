import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
import socket, struct, time
def q(name="example.com",qid=0x3333):
    h=struct.pack(">HHHHHH",qid,0x0100,1,0,0,0)
    qn=b"".join(bytes([len(p)])+p.encode() for p in name.split("."))+b"\x00"
    return h+qn+struct.pack(">HH",1,1)
def tcp(dst,port=53,ttl=None,timeout=4):
    s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    if ttl is not None: s.setsockopt(socket.IPPROTO_IP,socket.IP_TTL,ttl)
    s.settimeout(timeout); t0=time.perf_counter()
    try:
        s.connect((dst,port)); ct=(time.perf_counter()-t0)*1000
        p=q(); s.sendall(struct.pack(">H",len(p))+p)
        hdr=s.recv(2)
        if len(hdr)<2: return f"connected({ct:.1f}ms) but no DNS payload"
        n=struct.unpack(">H",hdr)[0]; data=b""
        while len(data)<n: 
            c=s.recv(n-len(data))
            if not c: break
            data+=c
        ms=(time.perf_counter()-t0)*1000
        _,fl,_,an,_,_=struct.unpack(">HHHHHH",data[:12])
        RC={0:"NOERROR",2:"SERVFAIL",3:"NXDOMAIN"}
        return f"DNS ANSWER rcode={RC.get(fl&0xF,fl&0xF)} ans={an} ad={(fl>>5)&1} connect={ct:.1f}ms total={ms:.1f}ms"
    except socket.timeout: return f"timeout ({(time.perf_counter()-t0)*1000:.1f}ms)"
    except OSError as e: return f"{e.__class__.__name__}/{e.errno}: {e} ({(time.perf_counter()-t0)*1000:.1f}ms)"
    finally: s.close()

print("=== TCP/53 — normal TTL ===")
for h in ["9.9.9.9","149.112.112.112","1.1.1.1","1.0.0.1","8.8.8.8","192.0.2.53","198.51.100.53","203.0.113.53","203.0.113.99",env("ROUTER_IP")]:
    print(f"  {h:<17} {tcp(h)}")
print()
print("=== TCP/53 — TTL=1 (yalnizca 1 hop otedeki cihaz yanitlayabilir) ===")
for h in ["9.9.9.9","1.1.1.1","8.8.8.8","203.0.113.99"]:
    print(f"  {h:<17} port53   ttl=1: {tcp(h,53,ttl=1,timeout=3)}")
    print(f"  {h:<17} port443  ttl=1: {tcp(h,443,ttl=1,timeout=3)}")
print()
print("=== TCP/443 — normal TTL (karsilastirma: gercek internete ulasiyor mu?) ===")
for h in ["9.9.9.9","1.1.1.1","203.0.113.99"]:
    print(f"  {h:<17} port443  ttl=64: {tcp(h,443,timeout=4)}")
