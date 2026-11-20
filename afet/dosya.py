"""Dosya okuma / yazma — betiklerin ortak biçimi.

JSON: yayın sitesine giden dosyalar sıkışık (boşluksuz), insanın okuyacağı
sonuç dosyaları girintili yazılır; Türkçe karakterler kaçışsız kalır.
İndirilen dosyalar atomik yazılır: yarıda kalan indirme önbellekte kalmaz."""
import json
import os


def json_oku(yol):
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def json_yaz(yol, veri, okunur: bool = False) -> int:
    """veri'yi yol'a yazar (klasörü yoksa açar); dosya boyutunu (bayt) döner.
    okunur=True girintili, değilse sıkışık yazar."""
    os.makedirs(os.path.dirname(yol) or ".", exist_ok=True)
    bicim = {"indent": 1} if okunur else {"separators": (",", ":")}
    with open(yol, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, **bicim)
    return os.path.getsize(yol)


def atomik_yaz(yol, govde: bytes):
    """govde'yi önce geçici dosyaya, sonra tek adımda yol'a yazar (klasörü yoksa açar)."""
    os.makedirs(os.path.dirname(yol) or ".", exist_ok=True)
    with open(yol + ".tmp", "wb") as f:
        f.write(govde)
    os.replace(yol + ".tmp", yol)
