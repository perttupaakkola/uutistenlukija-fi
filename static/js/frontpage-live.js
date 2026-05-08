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
      ['BTC', 'Bitcoin', 'crypto', 'bitcoin'],
      ['ETH', 'Ethereum', 'crypto', 'ethereum'],
      ['USDC', 'USD Coin', 'crypto', 'usd-coin'],
      ['SOL', 'Solana', 'crypto', 'solana']
    ],
    stocks: [
      ['BTC', 'Bitcoin', 'crypto', 'bitcoin'],
      ['ETH', 'Ethereum', 'crypto', 'ethereum'],
      ['XRP', 'XRP', 'crypto', 'ripple'],
      ['BNB', 'BNB', 'crypto', 'binancecoin']
    ],
    currencies: [
      ['EURUSD', 'EUR/USD', 'currency', 'usd'],
      ['EURSEK', 'EUR/SEK', 'currency', 'sek'],
      ['EURNOK', 'EUR/NOK', 'currency', 'nok'],
      ['BTC', 'Bitcoin/EUR', 'crypto', 'bitcoin']
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
        var price = typeof q.price === 'number' ? q.price : null;
        var change = typeof q.changePercent === 'number' ? q.changePercent : null;
        var changeText = change === null ? '' : ' <b class="' + (change < 0 ? 'negative' : '') + '">' + (change > 0 ? '+' : '') + change.toFixed(2).replace('.', ',') + ' %</b>';
        return '<div><dt>' + label + '</dt><dd>' + formatNumber(price) + changeText + '</dd></div>';
      }).join('');
    }

    function renderMarketRows(rows, cryptoData, currencyData) {
      var cryptoMap = cryptoData || {};
      var rates = ((currencyData || {}).eur) || {};
      var quoteMap = {};
      rows.forEach(function (row) {
        if (row[2] === 'crypto') {
          var q = cryptoMap[row[3]] || {};
          quoteMap[row[0]] = {
            price: q.eur,
            changePercent: typeof q.eur_24h_change === 'number' ? q.eur_24h_change : null
          };
        } else {
          quoteMap[row[0]] = { price: rates[row[3]], changePercent: null };
        }
      });
      renderRows(rows, quoteMap);
      return Object.keys(quoteMap).filter(function (key) { return typeof quoteMap[key].price === 'number'; }).length;
    }

    function loadSet(name) {
      var rows = marketSets[name] || marketSets.indices;
      skeleton(rows);
      if (note) note.textContent = 'Päivitetään markkinadataa…';

      var cryptoIds = rows.filter(function (row) { return row[2] === 'crypto'; }).map(function (row) { return row[3]; });
      var needsCurrency = rows.some(function (row) { return row[2] === 'currency'; });
      var cryptoUrl = 'https://api.coingecko.com/api/v3/simple/price?ids=' + encodeURIComponent(cryptoIds.join(',')) + '&vs_currencies=eur&include_24hr_change=true';
      var currencyUrl = 'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/eur.json';

      Promise.all([
        cryptoIds.length ? fetch(cryptoUrl, { cache: 'no-store' }).then(function (response) {
          if (!response.ok) throw new Error('crypto ' + response.status);
          return response.json();
        }).catch(function () { return {}; }) : Promise.resolve({}),
        needsCurrency ? fetch(currencyUrl, { cache: 'no-store' }).then(function (response) {
          if (!response.ok) throw new Error('currency ' + response.status);
          return response.json();
        }).catch(function () { return {}; }) : Promise.resolve({})
      ]).then(function (payloads) {
        var okCount = renderMarketRows(rows, payloads[0], payloads[1]);
        if (note) {
          note.textContent = okCount ? 'Viivästetty markkinadata, päivittyy selaimessa.' : 'Markkinadataa ei saatu juuri nyt. Siirry Talous-osioon lukemaan tuoreimmat uutiset.';
        }
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
