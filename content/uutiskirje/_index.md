---
title: "Tilaa uutiskirje"
description: "Tilaa Uutistenlukijan päivittäinen uutiskatsaus sähköpostiisi."
layout: "simple"
---

<div id="signup-status">

## Kiitos tilauksesta! ✅

Olet nyt Uutistenlukijan uutiskirjeen tilaaja.

**Mitä saat:**
- Päivän tärkeimmät uutiset kerran päivässä
- Ei mainoksia, ei roskapostia
- Voit peruuttaa koska tahansa

</div>

<script>
(function() {
  var params = new URLSearchParams(window.location.search);
  var status = params.get('status');
  var el = document.getElementById('signup-status');
  if (!el) return;
  if (status === 'invalid') {
    el.innerHTML = '<h2>⚠️ Virheellinen sähköpostiosoite</h2><p>Tarkista osoite ja yritä uudelleen.</p><p><a href="/">← Takaisin etusivulle</a></p>';
  } else if (status === 'error') {
    el.innerHTML = '<h2>⚠️ Virhe</h2><p>Jokin meni pieleen. Yritä myöhemmin uudelleen.</p><p><a href="/">← Takaisin etusivulle</a></p>';
  }
})();
</script>

[← Takaisin etusivulle](/)
