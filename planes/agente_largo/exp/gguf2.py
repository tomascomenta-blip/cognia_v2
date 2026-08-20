import struct, json
P=r"C:\Users\usuario\.cognia\models\Huihui-Qwythos-9B-Claude-Mythos-5-1M-abliterated-Q4_K.gguf"
f=open(P,"rb"); assert f.read(4)==b"GGUF"
ver,=struct.unpack("<I",f.read(4)); n_t,=struct.unpack("<Q",f.read(8)); n_kv,=struct.unpack("<Q",f.read(8))
FIX={0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,10:8,11:8,12:8}
FMT={0:"<B",1:"<b",2:"<H",3:"<h",4:"<I",5:"<i",6:"<f",7:"<?",10:"<Q",11:"<q",12:"<d"}
def rs():
    n,=struct.unpack("<Q",f.read(8)); return f.read(n).decode("utf-8","replace")
def rv(t):
    if t==8: return rs()
    if t==9:
        et,=struct.unpack("<I",f.read(4)); ln,=struct.unpack("<Q",f.read(8))
        if et==8:
            for _ in range(ln): rs()
            return f"<str array len={ln}>"
        if et==9: raise ValueError("nested")
        f.seek(FIX[et]*ln,1); return f"<array type={et} len={ln}>"
    return struct.unpack(FMT[t],f.read(FIX[t]))[0]
md={}
for _ in range(n_kv):
    k=rs(); t,=struct.unpack("<I",f.read(4)); v=rv(t)
    if not k.startswith("tokenizer."): md[k]=v
print(json.dumps(md,indent=1))
b=md.get("qwen3.block_count") or md.get("general.block_count")
kvh=md.get("qwen3.attention.head_count_kv"); kd=md.get("qwen3.attention.key_length"); vd=md.get("qwen3.attention.value_length")
if b and kvh and kd:
    per_tok=b*kvh*(kd+vd)*2  # f16 bytes/token
    print("\nKV f16 bytes/token:",per_tok, "| per 1k tok MiB:", round(per_tok*1024/1048576,2),
          "| 200192 ctx GiB:", round(per_tok*200192/1073741824,2))
