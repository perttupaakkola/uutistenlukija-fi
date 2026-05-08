(function () {
  'use strict';

  function fmtTemp(value) {
    if (typeof value !== 'number' || !isFinite(value)) return '-- °C';
    return Math.round(value) + ' °C';
  }

  function initWeather() {
    var widget = document.querySelector('[data-weather-widget]');
    if (!widget || !window.fetch) return;
    var tempEl = widget.querySelector('[data-weather-temp]');
    var cityEl = widget.querySelector('[data-weather-city-label]');
    var defaultCity = widget.getAttribute('data-weather-city') || 'Helsinki';

    function setLoading(city) {
      if (tempEl) tempEl.textContent = '-- °C';
      if (cityEl) cityEl.textContent = city || defaultCity;
      widget.classList.add('is-loading');
    }

    function renderWeather(lat, lon, city) {
      setLoading(city);
      var url = 'https://api.open-meteo.com/v1/forecast?latitude=' + encodeURIComponent(lat) +
        '&longitude=' + encodeURIComponent(lon) + '&current=temperature_2m&timezone=auto';
      return fetch(url, { cache: 'no-store' })
        .then(function (response) {
          if (!response.ok) throw new Error('weather ' + response.status);
          return response.json();
        })
        .then(function (data) {
          var current = data.current || data.current_weather || {};
          var temp = typeof current.temperature_2m === 'number' ? current.temperature_2m : current.temperature;
          if (tempEl) tempEl.textContent = fmtTemp(temp);
          if (cityEl) cityEl.textContent = city || defaultCity;
          widget.setAttribute('aria-label', 'Sää: ' + fmtTemp(temp) + ', ' + (city || defaultCity));
        })
        .catch(function () {
          if (tempEl) tempEl.textContent = '-- °C';
          if (cityEl) cityEl.textContent = city || defaultCity;
          widget.setAttribute('aria-label', 'Säätietoa ei voitu päivittää');
        })
        .finally(function () { widget.classList.remove('is-loading'); });
    }

    function useCurrentLocation() {
      if (!navigator.geolocation) return renderWeather(widget.dataset.weatherLat, widget.dataset.weatherLon, defaultCity);
      widget.classList.add('is-loading');
      navigator.geolocation.getCurrentPosition(function (pos) {
        renderWeather(pos.coords.latitude, pos.coords.longitude, 'Sijaintisi');
      }, function () {
        renderWeather(widget.dataset.weatherLat, widget.dataset.weatherLon, defaultCity);
      }, { maximumAge: 900000, timeout: 5000, enableHighAccuracy: false });
    }

    renderWeather(widget.dataset.weatherLat, widget.dataset.weatherLon, defaultCity);
    widget.addEventListener('click', useCurrentLocation);
  }

  var marketSets = {
    indices: [
      ['^OMXH25', 'OMX Helsinki 25'],
      ['^OMX', 'OMX Stockholm 30'],
      ['^GSPC', 'S&P 500'],
      ['^NDX', 'Nasdaq 100']
    ],
    stocks: [
      ['NOKIA.HE', 'Nokia'],
      ['KNEBV.HE', 'Kone'],
      ['NESTE.HE', 'Neste'],
      ['SAMPO.HE', 'Sampo']
    ],
    currencies: [
      ['EURUSD=X', 'EUR/USD'],
      ['EURSEK=X', 'EUR/SEK'],
      ['EURNOK=X', 'EUR/NOK'],
      ['BTC-EUR', 'Bitcoin/EUR']
    ]
  };

  function formatNumber(value) {
    if (typeof value !== 'number' || !isFinite(value)) return '—';
    return new Intl.NumberFormat('fi-FI', { maximumFractionDigits: value >= 100 ? 2 : 4 }).format(value);
  }

  function initMarkets() {
    var widget = document.querySelector('[data-market-widget]');
    if (!widget || !window.fetch) return;
    var list = widget.querySelector('[data-market-list]');
    var note = widget.querySelector('[data-market-note]');
    var tabs = Array.prototype.slice.call(widget.querySelectorAll('[data-market-tab]'));
    if (!list || !tabs.length) return;

    function skeleton(rows) {
      list.innerHTML = rows.map(function (row) {
        return '<div><dt>' + row[1] + '</dt><dd data-symbol="' + row[0] + '">Päivitetään…</dd></div>';
      }).join('');
    }

    function renderRows(rows, quoteMap) {
      list.innerHTML = rows.map(function (row) {
        var symbol = row[0];
        var label = row[1];
        var q = quoteMap[symbol] || {};
        var price = typeof q.regularMarketPrice === 'number' ? q.regularMarketPrice : q.regularMarketPreviousClose;
        var change = typeof q.regularMarketChangePercent === 'number' ? q.regularMarketChangePercent : null;
        var changeText = change === null ? '' : ' <b class="' + (change < 0 ? 'negative' : '') + '">' + (change > 0 ? '+' : '') + change.toFixed(2).replace('.', ',') + ' %</b>';
        return '<div><dt>' + label + '</dt><dd>' + formatNumber(price) + changeText + '</dd></div>';
      }).join('');
    }

    function loadSet(name) {
      var rows = marketSets[name] || marketSets.indices;
      skeleton(rows);
      if (note) note.textContent = 'Päivitetään markkinadataa…';
      var symbols = rows.map(function (r) { return r[0]; }).join(',');
      var url = 'https://query1.finance.yahoo.com/v7/finance/quote?symbols=' + encodeURIComponent(symbols);
      fetch(url, { cache: 'no-store' })
        .then(function (response) {
          if (!response.ok) throw new Error('markets ' + response.status);
          return response.json();
        })
        .then(function (data) {
          var result = (((data || {}).quoteResponse || {}).result) || [];
          var quoteMap = {};
          result.forEach(function (q) { if (q.symbol) quoteMap[q.symbol] = q; });
          renderRows(rows, quoteMap);
          if (note) note.textContent = 'Viivästetty markkinadata, päivittyy selaimessa.';
        })
        .catch(function () {
          if (note) note.textContent = 'Markkinadataa ei saatu juuri nyt. Siirry Talous-osioon lukemaan tuoreimmat uutiset.';
          list.innerHTML = rows.map(function (row) {
            return '<div><dt>' + row[1] + '</dt><dd>Ei saatavilla</dd></div>';
          }).join('');
        });
    }

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        tabs.forEach(function (other) {
          var active = other === tab;
          other.classList.toggle('is-active', active);
          other.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        loadSet(tab.getAttribute('data-market-tab'));
      });
    });

    loadSet('indices');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initWeather();
      initMarkets();
    });
  } else {
    initWeather();
    initMarkets();
  }
})();
