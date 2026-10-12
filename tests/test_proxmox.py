import json
from types import SimpleNamespace
import httpx
import pytest
from academy.proxmox import Proxmox


def adapter(handler):
    obj = Proxmox.__new__(Proxmox)
    obj.s = SimpleNamespace(pve_node="training", pve_storage="local-lvm", pve_bridge="vmbr1", console_source="192.0.2.10")
    obj.client = httpx.Client(base_url="https://pve.invalid/api2/json", transport=httpx.MockTransport(handler))
    return obj


def session():
    return SimpleNamespace(id="owned-session",vmid=5000,ip="192.0.2.10",public_key="ssh-rsa AAAATEST")


def test_exec_uses_json_argument_array_and_decoded_output():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/config"):
            data = {"description":"academy-session:owned-session"}
        elif request.url.path.endswith("/exec"):
            assert json.loads(request.content)["command"] == ["/usr/local/sbin/academy-lab","check","net-01-link-down"]
            data = {"pid":42}
        else:
            data = {"exited":1,"exitcode":0,"out-data":"PASS\n","err-data":""}
        return httpx.Response(200,json={"data":data})
    provider = adapter(handler)
    assert provider.exec(session(), ["/usr/local/sbin/academy-lab","check","net-01-link-down"]) == (0,"PASS\n")


def test_delete_refuses_unowned_and_auth_errors():
    for status, payload in [(200,{"data":{"description":"foreign"}}),(401,{"error":"unauthorized"})]:
        calls = []
        def handler(request):
            calls.append(request.method)
            return httpx.Response(status,json=payload)
        with pytest.raises(RuntimeError):
            adapter(handler).delete(session())
        assert calls == ["GET"]


def test_absent_vm_is_not_deleted():
    provider = adapter(lambda request: httpx.Response(500,text="configuration file does not exist"))
    provider.delete(session())


def test_pool_scoped_clone_does_not_require_a_stale_vmid_acl():
    seen = []
    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path.endswith("/5000/config"):
            return httpx.Response(403, json={"error": "permission denied"})
        if request.url.path.endswith("/9006/config"):
            return httpx.Response(200, json={"data": {"template": 1}})
        return httpx.Response(200, json={"data": None})
    provider = adapter(handler)
    assert provider.owned(session()) is None
    provider.clone(session(), SimpleNamespace(template_id=9006))
    clone = next(body for method, path, body in seen if method == "POST" and path.endswith("/clone"))
    assert clone["pool"] == "academy-learners"


def test_configuration_preserves_mac_and_enforces_isolation():
    calls=[]
    def handler(request):
        payload=json.loads(request.content) if request.content else {}
        calls.append((request.method,request.url.path,payload))
        if request.url.path.endswith("/config") and request.method=="GET":
            data={"description":"academy-session:owned-session","net0":"virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1"}
        elif request.url.path.endswith("/status/current"):
            data={"status":"stopped"}
        elif request.method=="GET": data=[]
        else: data=None
        return httpx.Response(200,json={"data":data})
    adapter(handler).configure(session(),SimpleNamespace(cores=2,memory=2048))
    vmconfig=next(p for method,path,p in calls if method=="PUT" and path.endswith("/config"))
    assert vmconfig["net0"]=="virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1,firewall=1"
    assert vmconfig["ipconfig0"]=="ip=192.0.2.10/24"
    firewall=next(p for method,path,p in calls if path.endswith("/options"))
    assert firewall["policy_in"]==firewall["policy_out"]=="DROP"
    rule=next(p for method,path,p in calls if method=="POST" and path.endswith("/rules"))
    assert rule["source"]=="192.0.2.10/32" and rule["dport"]=="22"
