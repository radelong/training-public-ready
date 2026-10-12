FROM ubuntu:26.04
COPY assets/debs /opt/offline-debs
RUN printf 'deb [trusted=yes] file:/opt/offline-debs ./\n' >/tmp/offline.list \
    && apt-get -o Dir::Etc::sourcelist=/tmp/offline.list -o Dir::Etc::sourceparts=- update \
    && apt-get -y --no-install-recommends -o Dir::Etc::sourcelist=/tmp/offline.list -o Dir::Etc::sourceparts=- install procps \
    && rm -rf /opt/offline-debs /var/lib/apt/lists/* /tmp/offline.list
CMD ["sleep", "infinity"]
