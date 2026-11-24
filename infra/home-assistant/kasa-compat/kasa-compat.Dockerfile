ARG HA_BASE_IMAGE=ghcr.io/home-assistant/home-assistant@sha256:f0baa7922ecec7790c40c41baf08ab218b6ab8db5f96dc03b03a0ae33d987c3d
FROM ${HA_BASE_IMAGE}
LABEL ai.inneros.compatibility="python-kasa-0.10.2-iot-klap-v2"
COPY kasa_backport_20261124.py check_backport.py /opt/inneros-kasa-compat/
RUN python3 /opt/inneros-kasa-compat/kasa_backport_20261124.py --apply --backup-dir /opt/inneros-kasa-compat/stock \
 && KASA_STOCK_SOURCE=/opt/inneros-kasa-compat/stock/device_factory.py KASA_EXPECT_PATCHED=1 python3 /opt/inneros-kasa-compat/check_backport.py
