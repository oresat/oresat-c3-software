% rebase('base.tpl', name='Reset')
<button onclick="poweroff()">Poweroff</button>
<button onclick="softReset()">Soft Reset</button>
<button onclick="hardReset()">Hard Reset</button>
<button onclick="factoryReset()">Factory Reset</button>
<script>
  const RESET_URL = `http://${window.location.host}/data/reset`;

  function reset(value) {
    putData(RESET_URL, {"reset": value});
  }

  function poweroff() { reset("POWEROFF"); }
  function softReset() { reset("SOFT_RESET"); }
  function hardReset() { reset("HARD_RESET"); }
  function factoryReset() { reset("FACTORY_RESET"); }
</script>
