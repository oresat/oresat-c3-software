% rebase('base.tpl', name='Beacon')
<style>
  table {
    font-family: arial, sans-serif;
    border-collapse: collapse;
    margin-left: auto;
    margin-right: auto;
  }
  thead {
    font-weight: bold;
  }
  td, th {
    border: 1px solid #dddddd;
    text-align: left;
    padding: 8px;
  }
</style>
<td><button id="beacon" onclick="beacon()">Send Beacon</button></td>
<script>
  const BEACON_URL = `http://${window.location.host}/data/beacon`;

  async function beacon() {
    await putData(BEACON_URL, {});
  }
</script>
