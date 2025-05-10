<!DOCTYPE html>
<html lang="en">
  <head>
    <title>{{mission}} C3</title>
  </head>
  <body>
    <style>
      html, body {
        margin: 0;
      }
      #headerGrid {
        display: grid;
        grid-template-columns: 25% 50% 25%;
        align-items: center;
        padding-left: 5px;
        padding-right: 5px;
        border-bottom: 1px solid black;
      }
      #headerCenter {
        text-align: center;
      }
      #headerRight {
        text-align: right;
      }
      #links {
        text-align: center;
      }
      #content {
        text-align: center;
      }
    </style>
    <div id="headerGrid">
      <div id="headerLeft">
        <b>CANd: </b>
        <text id="candStatus"></text>
        <br/>
        <b>CAN Bus: </b>
        <text id="canBusStatus"></text>
      </div>
      <div id="headerCenter">
        <h2>{{mission}} C3</h2>
        <div id="links">
          <a href="/">Home</a>
          % for url_name, nice_name in routes:
          <text> | <text>
          <a href="/{{url_name}}">{{nice_name}}</a>
          % end
          <br/>
          <br/>
        </div>
      </div>
      <div id="headerRight">
        <label for="flightMode"><b>Flight Mode</b>: </label>
        <input type="checkbox" id="flightMode" onclick="toggleFlightMode()"></input>
      </div>
    </div>
    <script>
      async function getData(url) {
        return await fetch(url)
          .then(response => response.json())
          .then(data => {
              return data;
          });
      }

      async function putData(url, data) {
        const options = {
          "method": "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          "body": JSON.stringify(data),
        };
        return await fetch(url, options);
      }
    </script>
    <div id="content">
      <h3>{{name}}</h3>
      {{!base}}
    </div>
    <script>
      const STATUS_URL = `http://${window.location.host}/data/status`;

      const flightModeCheckbox = document.getElementById("flightMode")
      const candStatusText = document.getElementById("candStatus")
      const canBusStatusText = document.getElementById("canBusStatus")

      async function updateHeader() {
        const data = await getData(STATUS_URL);
        flightModeCheckbox.checked = data.FLIGHT_MODE;
        candStatusText.innerHTML = data.CAND_STATUS;
        canBusStatusText.innerHTML = data.CAN_BUS_STATUS;
      }

      async function toggleFlightMode() {
        await putData(STATUS_URL, {FLIGHT_MODE: flightModeCheckbox.checked})
      }

      updateHeader();
      const updateHeaderInterval = setInterval(function() {
        updateHeader();
      }, 1000);
    </script>
  </body>
</html>
