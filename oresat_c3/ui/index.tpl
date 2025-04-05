% rebase('base.tpl', name='Home')
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
<table>
  <thead>
    <tr>
      <td>Name</td>
      <td>Version</td>
    </tr>
  </thead>
  <tbody>
      <td>OreSat C3 App</td>
      <td>{{version}}</td>
  </tbody>
  <tbody>
      <td>OreSat C3 Hardware</td>
      <td>{{hw_version}}</td>
  </tbody>
  <tbody>
      <td>OreSat CANopend</td>
      <td>{{canopend_version}}</td>
  </tbody>
</table>
