"""JSON dosyası okuma / yazma — betiklerin ortak biçimi.

Yayın sitesine giden dosyalar sıkışık (boşluksuz), insanın okuyacağı sonuç
dosyaları girintili yazılır; Türkçe karakterler kaçışsız kalır."""
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
