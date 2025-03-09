% rebase('base.tpl', name='Keys')
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
<div id="activeKeySelect">
  <b>Active Key:</b>
  <select id="activeKey">
    <option>0</option>
    <option>1</option>
    <option>2</option>
    <option>3</option>
  </select>
</div>
<br/>
<table>
  <thead>
    <tr>
      <td>Number</td>
      <td>Hex Value (32 bytes)</td>
      <td>Set<td>
    </tr>
  </thead>
  <tbody>
      <td>0</td>
      <td><input type="text" maxlength=64 size=64 id="key0Value"></input></td>
      <td></td>
  </tbody>
  <tbody>
      <td>1</td>
      <td><input type="text" maxlength=64 size=64 id="key1Value"></input></td>
      <td></td>
  </tbody>
  <tbody>
      <td>2</td>
      <td><input type="text" maxlength=64 size=64 id="key2Value"></input></td>
      <td></td>
  </tbody>
  <tbody>
      <td>3</td>
      <td><input type="text" maxlength=64 size=64 id="key3Value"></input></td>
      <td></td>
  </tbody>
</table>
<br/>
<td><button id="update" onclick="update()">Update</button></td>
<script>
  const KEYS_URL = `http://${window.location.host}/data/keys`;

  async function update() {
    await putData(KEYS_URL, {
      "EDL_ACTIVE_CRYPTO_KEY": parseInt(document.getElementById("activeKey").value),
      "EDL_CRYPTO_KEY_0": document.getElementById("key0Value").value,
      "EDL_CRYPTO_KEY_1": document.getElementById("key1Value").value,
      "EDL_CRYPTO_KEY_2": document.getElementById("key2Value").value,
      "EDL_CRYPTO_KEY_3": document.getElementById("key3Value").value,
    });
  }

  async function getKeys() {
    const data = await getData(KEYS_URL);
    document.getElementById("activeKey").selectedIndex = data.EDL_ACTIVE_CRYPTO_KEY;
    document.getElementById("key0Value").value = data.EDL_CRYPTO_KEY_0;
    document.getElementById("key1Value").value = data.EDL_CRYPTO_KEY_1;
    document.getElementById("key2Value").value = data.EDL_CRYPTO_KEY_2;
    document.getElementById("key3Value").value = data.EDL_CRYPTO_KEY_3;
  }

  getKeys();
</script>
