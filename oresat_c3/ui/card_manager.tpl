% rebase('base.tpl', name='Card Manager')
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
<b>OPD Status:</b>
<span id="systemStatus">ENABLED</span>
<button id="enableSystemButton" onclick="enableSystem()">Disable System</button>
<br />
<br />
<div id="cardMgrTableDiv">
  <b>UART Card:</b>
  <select id="uartCardSelect" onchange="uartSelect()">
    <option value=0>NONE</option>
  </select>
  <br />
  <br />
  <table id="cardMgrTable">
    <thead>
      <tr>
        <td>Card</td>
        <td>Node Id</td>
        <td>Status</td>
        <td>OPD Address</td>
        <td>Control</td>
      </tr>
    </thead>
    <tbody>
      <td>C3</td>
      <td>0x1</td>
      <td>ON</td>
      <td></td>
      <td></td>
    </tbody>
    <tbody>
    </tbody>
  </table>
</div>
<script>
  const NM_URL = `http://${window.location.host}/data/card-manager`;

  async function buildTable() {
    const data = await getData(NM_URL);

    let tbodyRef = document.getElementById("cardMgrTable").getElementsByTagName("tbody")[0];
    let uartCardSelect = document.getElementById('uartCardSelect');
    for (const card of data.cards) {
      let newRow = tbodyRef.insertRow();

      let newCell = newRow.insertCell();
      let newText = document.createTextNode(card.name);
      newCell.appendChild(newText);

      let newCell4 = newRow.insertCell();
      let upperHex = parseInt(card.node_id).toString(16).toUpperCase()
      if (upperHex !== "0") {
        upperHex = `0x${upperHex}`;
      } else  {
        upperHex = "";
      }
      let newText4 = document.createTextNode(upperHex);
      newCell4.appendChild(newText4);

      let newCell2 = newRow.insertCell();
      let span = document.createElement("span");
      span.id = `card${card.node_id}`;
      span.innerText = card.status;
      newCell2.appendChild(span);

      let newCell5 = newRow.insertCell();
      upperHex = parseInt(card.opd_addr).toString(16).toUpperCase()
      if (upperHex !== "0") {
        upperHex = `0x${upperHex}`;
      } else  {
        upperHex = "";
      }
      let newText5 = document.createTextNode(upperHex);
      newCell5.appendChild(newText5);

      let newCell3 = newRow.insertCell();
      if (card.opd_addr !== 0 && card.node_id !== 0) {
        let select = document.createElement("select");
        select.id = `card${card.node_id}Select`

        let opt = document.createElement('option');
        opt.value = "DISABLE";
        opt.innerHTML = "DISABLE";
        select.appendChild(opt);

        opt = document.createElement('option');
        opt.value = "ENABLE";
        opt.innerHTML = "ENABLE";
        select.appendChild(opt);

        opt = document.createElement('option');
        opt.value = "BOOTLOADER";
        opt.innerHTML = "BOOTLOADER";
        select.appendChild(opt);
        if (card.processor != "STM32") {
            opt.style.display = "none";
        }

        select.style.with = "auto";
        select.value = null;
        select.onchange = function(){console.log(card); cardOnSelect(card)};
        newCell3.appendChild(select);

        // add to UART cards list
        opt = document.createElement('option');
        opt.value = card.opd_addr;
        opt.innerHTML = card.name;
        uartCardSelect.appendChild(opt);
      }
    }
  }

  async function cardOnSelect(card) {
    const select = document.getElementById(`card${card.node_id}Select`);
    const data = {
      "card": `${card.name}`,
      "state": select.value,
    };
    await putData(NM_URL, data);
    let state = "OFF";
    if (select.value === "ENABLE") {
      state = "BOOT";
    } else if (select.value === "BOOTLOADER") {
      state = "BOOTLOADER";
    }
    select.value = null;
    updateCard(card.node_id, state);
  }

  async function update() {
    const statusSpan = document.getElementById("systemStatus");
    const enableButton = document.getElementById("enableSystemButton");

    const data = await getData(NM_URL);
    for (const card of data.cards) {
      updateCard(card.node_id, card.status);
    }

    const status = data.opd_status;
    statusSpan.innerText = status;
    const cardDiv = document.getElementById("cardMgrTableDiv");
    if ((status === "ENABLED") || (status === "FAULT")) {
      enableButton.innerText = "Disable System";
      cardDiv.style.display = "inline";
    } else {
      enableButton.innerText = "Enable System";
      cardDiv.style.display = "none";
    }

    const select = document.getElementById("uartCardSelect");
    select.value = data.opd_uart_card_select;
  }

  function updateCard(card, status) {
    const span = document.getElementById(`card${card}`);
    const button = document.getElementById(`card${card}Button`);

    span.innerText = status;

    if (button === null) {
      return;
    }

    switch (status) {
    case "OFF":
      button.innerText = "Enable";
      button.disabled = false;
      break;
    case "BOOT":
    case "ON":
      button.innerText = "Disable";
      button.disabled = false;
      break;
    default:
      button.innerText = "Enable";
      button.disabled = true;
    }
  }

  async function enableSystem() {
    const status = document.getElementById("systemStatus").innerText;
    let enable = "ENABLED";
    if ((status === "ENABLED") || (status === "FAULT")) {
      enable = "DISABLED";
    }
    await putData(NM_URL, {"opd_status": enable});
    update();
  }

  async function uartSelect() {
    const select = document.getElementById("uartCardSelect");
    await putData(NM_URL, {"opd_uart_card_select": Number(select.value)});
  }

  buildTable();
  update();
  const interval = setInterval(function() {
    update();
  }, 1000);
</script>
