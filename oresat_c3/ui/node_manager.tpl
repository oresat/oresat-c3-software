% rebase('base.tpl', name='Node Manager')
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
<div id="nodeMgrTableDiv">
  <b>UART Node:</b>
  <select id="uartNodeSelect" onchange="uartSelect()">
    <option value=0>NONE</option>
  </select>
  <br />
  <br />
  <table id="nodeMgrTable">
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
  const NM_URL = `http://${window.location.host}/data/node-manager`;

  async function buildTable() {
    const data = await getData(NM_URL);

    let tbodyRef = document.getElementById("nodeMgrTable").getElementsByTagName("tbody")[0];
    let uartNodeSelect = document.getElementById('uartNodeSelect');
    for (const node of data.nodes) {
      let newRow = tbodyRef.insertRow();

      let newCell = newRow.insertCell();
      let newText = document.createTextNode(node.name);
      newCell.appendChild(newText);

      let newCell4 = newRow.insertCell();
      let upperHex = parseInt(node.node_id).toString(16).toUpperCase()
      if (upperHex !== "0") {
        upperHex = `0x${upperHex}`;
      } else  {
        upperHex = "";
      }
      let newText4 = document.createTextNode(upperHex);
      newCell4.appendChild(newText4);

      let newCell2 = newRow.insertCell();
      let span = document.createElement("span");
      span.id = `node${node.node_id}`;
      span.innerText = node.status;
      newCell2.appendChild(span);

      let newCell5 = newRow.insertCell();
      upperHex = parseInt(node.opd_addr).toString(16).toUpperCase()
      if (upperHex !== "0") {
        upperHex = `0x${upperHex}`;
      } else  {
        upperHex = "";
      }
      let newText5 = document.createTextNode(upperHex);
      newCell5.appendChild(newText5);

      let newCell3 = newRow.insertCell();
      if (node.opd_addr !== 0 && node.node_id !== 0) {
        let select = document.createElement("select");
        select.id = `node${node.node_id}Select`

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
        if (node.processor != "STM32") {
            opt.style.display = "none";
        }

        select.style.with = "auto";
        select.value = null;
        select.onchange = function(){console.log(node); nodeOnSelect(node)};
        newCell3.appendChild(select);

        // add to UART nodes list
        opt = document.createElement('option');
        opt.value = node.opd_addr;
        opt.innerHTML = node.name;
        uartNodeSelect.appendChild(opt);
      }
    }
  }

  async function nodeOnSelect(node) {
    const select = document.getElementById(`node${node.node_id}Select`);
    const data = {
      "node": `${node.name}`,
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
    updateNode(node.node_id, state);
  }

  async function update() {
    const statusSpan = document.getElementById("systemStatus");
    const enableButton = document.getElementById("enableSystemButton");

    const data = await getData(NM_URL);
    for (const node of data.nodes) {
      updateNode(node.node_id, node.status);
    }

    const status = data.opd_status;
    statusSpan.innerText = status;
    const nodeDiv = document.getElementById("nodeMgrTableDiv");
    if ((status === "ENABLED") || (status === "FAULT")) {
      enableButton.innerText = "Disable System";
      nodeDiv.style.display = "inline";
    } else {
      enableButton.innerText = "Enable System";
      nodeDiv.style.display = "none";
    }

    const select = document.getElementById("uartNodeSelect");
    select.value = data.opd_uart_node_select;
  }

  function updateNode(node, status) {
    const span = document.getElementById(`node${node}`);
    const button = document.getElementById(`node${node}Button`);

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
    const select = document.getElementById("uartNodeSelect");
    await putData(NM_URL, {"opd_uart_node_select": Number(select.value)});
  }

  buildTable();
  update();
  const interval = setInterval(function() {
    update();
  }, 1000);
</script>
