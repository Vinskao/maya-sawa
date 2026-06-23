# IBKR Client Portal Gateway (CPAPI v1)
#
# Static Java app downloaded from IBKR. It proxies to api.ibkr.com and holds the
# authenticated session in memory. The session is established via a browser
# login (see README) and is NOT persisted across restarts — restarting the pod
# requires re-authenticating.
FROM eclipse-temurin:21-jre

WORKDIR /opt/clientportal.gw

# Vendored gateway runtime (bin/ dist/ build/ root/ doc/). root/conf.yaml is the
# in-cluster config: listenPort 5000, ips.allow includes the pod CIDR.
COPY gateway/ ./

# run.sh resolves the classpath relative to the gateway root.
RUN sed -i 's/\r$//' bin/run.sh && chmod +x bin/run.sh

EXPOSE 5000

# Self-signed TLS on 5000; maya-sawa connects with verify=False.
CMD ["bin/run.sh", "root/conf.yaml"]
