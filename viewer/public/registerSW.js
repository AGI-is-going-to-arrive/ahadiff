(function () {
  if (!('serviceWorker' in navigator)) return;

  var hadController = Boolean(navigator.serviceWorker.controller);
  var reloading = false;

  navigator.serviceWorker.addEventListener('controllerchange', function () {
    if (!hadController || reloading) return;
    reloading = true;
    window.location.reload();
  });

  function activateWaitingWorker(registration) {
    if (registration.waiting) {
      registration.waiting.postMessage({ type: 'SKIP_WAITING' });
    }
  }

  window.addEventListener('load', function () {
    navigator.serviceWorker.register('./sw.js', { scope: './' })
      .then(function (registration) {
        activateWaitingWorker(registration);
        registration.addEventListener('updatefound', function () {
          var worker = registration.installing;
          if (!worker) return;
          worker.addEventListener('statechange', function () {
            if (worker.state === 'installed') activateWaitingWorker(registration);
          });
        });
      })
      .catch(function () {});
  });
}());
