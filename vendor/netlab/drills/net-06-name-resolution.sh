DRILL_TITLE="Name resolves to the wrong address"
DRILL_MODULE="net"
DRILL_LEVEL=2
DRILL_TIME="10 min"
DRILL_TOOLS="getent, resolvectl, /etc/hosts, /etc/nsswitch.conf"
DRILL_BRIEF="An application that talks to http://web.lab.local:8080/ started
timing out this morning. Using the IP address 10.10.2.10 directly works fine.
Nothing about the network path has changed."
DRILL_GOAL="Make web.lab.local resolve to 10.10.2.10 again from the client, and
make http://web.lab.local:8080/health succeed."

drill_break() {
  printf '%s\n' '127.0.0.1   localhost' > "/etc/netns/$NS_CLIENT/hosts"
  printf '%s\n' '10.10.9.99  web.lab.local web' >> "/etc/netns/$NS_CLIENT/hosts"
  printf '%s\n' '10.10.1.1   gw.lab.local gw' >> "/etc/netns/$NS_CLIENT/hosts"
}

drill_verify() {
  t_resolves_to client web.lab.local "$SERVER_IP" || return 1
  t_http client "http://web.lab.local:$HTTP_PORT/health"
}

drill_hint() { cat <<'H'
"The IP works but the name does not" is always a resolution problem, never
a routing problem. Separate the two questions.

What does the name resolve to, going through the same path the application
uses (nsswitch, so hosts file AND DNS)?
  sudo netlab exec client getent hosts web.lab.local

What does pure DNS say (bypassing /etc/hosts)?
  sudo netlab exec client dig +short web.lab.local

If those two disagree, something local is overriding DNS. Where does the
resolver look first?
  sudo netlab exec client cat /etc/nsswitch.conf
  sudo netlab exec client cat /etc/hosts

In this lab each namespace has its own /etc/hosts, stored on the host at
/etc/netns/nl-client/hosts.
H
}

drill_solution() { cat <<'S'
Diagnose:
  sudo netlab exec client getent hosts web.lab.local
    10.10.9.99   web.lab.local web        <-- wrong address

  sudo netlab exec client ping -c1 10.10.9.99
    ... 100% packet loss                  <-- nothing lives there

  sudo netlab exec client cat /etc/nsswitch.conf
    hosts: files dns                      <-- files are consulted FIRST

  sudo netlab exec client cat /etc/hosts
    10.10.9.99  web.lab.local web         <-- the culprit

Fix -- edit the namespace hosts file on the host:
  sudo sed -i 's/^10\.10\.9\.99/10.10.2.10/' /etc/netns/nl-client/hosts
  sudo netlab exec client getent hosts web.lab.local

Confirm:
  sudo netlab exec client curl -s http://web.lab.local:8080/health
    netlab-ok

On a real Ubuntu 22.04/24.04 machine the resolution chain is:
  /etc/nsswitch.conf      decides the order: files, then dns
  /etc/hosts              static overrides, wins over DNS by default
  /etc/resolv.conf        usually a symlink to a systemd-resolved stub
                          pointing at 127.0.0.53
  resolvectl status       shows the REAL upstream servers and per-link
                          search domains -- read this, not resolv.conf
  resolvectl query web.lab.local
  resolvectl flush-caches clears a poisoned cache
S
}

drill_debrief() { cat <<'D'
Split every "cannot connect" report in two immediately:

  1. Does the name resolve, and to what?   getent hosts / dig +short
  2. Does the address answer?              ping / curl against the IP

Ninety percent of the time one of the two is obviously fine and you have
halved the problem in ten seconds.

Use "getent hosts" rather than "dig" when you want to know what the
APPLICATION will see: getent goes through nsswitch, so it honours
/etc/hosts, mDNS and any other configured source. "dig" talks straight to
a DNS server and will happily disagree with the application.

On systemd-resolved systems /etc/resolv.conf almost always says
"nameserver 127.0.0.53" and tells you nothing useful. "resolvectl status"
is the command that shows the real upstream resolvers.
D
}
