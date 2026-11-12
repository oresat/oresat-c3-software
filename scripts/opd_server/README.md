# OPD Server and Client

### Setup
Start and background the opd server

```
sudo python3 opd_server.py
```

Background it with `ctrl-z` and then `bg`. 
You should see a log message saying `Waiting for connection`.

The OPD Server must run in the background to keep the OPD I2C line powered.

### Usage

First re-scan all the nodes
```
python3 opd_client.py scan
```

Then print the status of all nodes. 
```
python3 opd_client.py status
```
Available nodes should be in the `DISABLED` state

Enable as many nodes as you please
```
python3 opd_client.py enable rw_1 rw_2 rw_3 rw_4
```

Disable as many nodes as you please
```
python3 opd_client.py disable rw_1 rw_2 rw_3 rw_4
```

### Teardown

Foreground the server with `fg` or use the opd client command:

```
python3 opd_client.py end
```
