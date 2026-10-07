"""Uzmanlara gösterilen çalışma bilgilendirme metni. Model adı içermez."""

import streamlit as st

STUDY_INFO_MARKDOWN = """
Bu çalışmada, gestasyonel diyabetle ilgili Türkçe sorulara yapay zekâ
modellerinin verdiği yanıtları uzman gözüyle değerlendirmenizi rica ediyoruz.

**Kör değerlendirme**
- Her yanıt yalnızca bir kodla (ör. R017) gösterilir; hangi modelin yazdığı gösterilmez.
- Lütfen yanıtın hangi modelden geldiğini tahmin etmeye veya araştırmaya çalışmayın.
- Size yalnızca uzmanlık alanınıza atanan eksenlerdeki yanıtlar gelir.

**Her yanıt için beş bölüm**
1. **GQS:** Genel kalite, 1 (çok düşük) ile 5 (mükemmel) arası.
2. **Kapsamlılık:** Soruya özel maddelerden yanıtta karşılananları işaretleyin. Kritik maddeler ayrı gösterilir.
3. **Kültürel uygunluk (CAS):** 0 (uyumsuz), 1 (kısmen), 2 (uyumlu). Her soruda yalnızca o soruyla ilgili maddeler gösterilir (1 ile 4 madde arası); "Kültürel varsayımlardan kaçınma" her soruda vardır. Gösterilmeyen madde "konu dışı" sayılır, 0 puan anlamına gelmez.
4. **Güvenlik:** Hastaya zarar verebilecek bir bilgi varsa "Evet" seçip kısaca açıklayın.
5. **DISCERN:** Sekiz madde, 1 (hiç) ile 5 (tam) arası.

Yeni puanlamada hiçbir alanda ön seçim yoktur; zorunlu alanlar doldurulmadan puan gönderilemez.

**Kaydetme**
- "Gönder ve sonraki" düğmesi puanı kaydeder ve bir sonraki yanıta geçer.
- İstediğiniz zaman ara verebilirsiniz; yeniden girişte kaldığınız yerden devam edersiniz.
- Gönderdiğiniz puanı paneldeki "Puanladıklarım" bölümünden düzeltebilirsiniz; düzeltme önceki puanın yerine geçer.
"""


def render_study_info(expanded: bool) -> None:
    """Bilgilendirme metnini açılır kutu içinde gösterir."""
    with st.expander("Çalışma hakkında bilgilendirme", expanded=expanded):
        st.markdown(STUDY_INFO_MARKDOWN)
