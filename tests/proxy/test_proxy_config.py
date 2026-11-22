from pathlib import Path

RAIZ = Path(__file__).parents[2]
COMPOSE = (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
NGINX = (RAIZ / "infra/nginx/nginx.conf").read_text(encoding="utf-8")
HTTP = (RAIZ / "infra/nginx/conf.d/orvia-http.conf").read_text(encoding="utf-8")
TLS = (RAIZ / "infra/nginx/conf.d/orvia-tls.conf").read_text(encoding="utf-8")

SERVICIOS = {
    "app", "auth", "devoluciones", "logistica", "inspecciones",
    "disposicion-inventario", "reembolsos-costos", "ventas-catalogos", "evidencias",
    "analisis-auditoria", "reportes-analitica", "causa-raiz",
    "sincronizacion", "proveedores", "integraciones-monitoreo",
    "clasificacion-motivos",
}


def test_solo_proxy_publica_puertos_de_aplicacion():
    assert '"0.0.0.0:${PROXY_HTTP_PORT:-80}:8080"' in COMPOSE
    for nombre in SERVICIOS:
        inicio = COMPOSE.index(f"  {nombre}:\n")
        siguientes = [p for p in (COMPOSE.find(f"\n  {otro}:\n", inicio + 1)
                                   for otro in SERVICIOS | {"proxy"}) if p >= 0]
        fin = min(siguientes, default=len(COMPOSE))
        bloque = COMPOSE[inicio:fin]
        assert "    ports:" not in bloque, nombre
        assert '    expose: ["8000"]' in bloque, nombre


def test_backend_no_publica_puertos_y_proxy_tiene_dos_redes():
    # No se usa `internal: true`: evidencias e integraciones necesitan salida a
    # GCS/POS/ERP. La ausencia de `ports` impide la entrada directa desde host.
    assert "    networks: [default, public]" in COMPOSE


def test_proxy_se_actualiza_si_compose_recrea_un_backend():
    for nombre in SERVICIOS:
        assert f"{nombre}: {{condition: service_started, restart: true}}" in COMPOSE


def test_todas_las_api_tienen_destino_en_http_y_tls():
    destinos = {
        "auth": "auth", "devoluciones": "devoluciones", "logistica": "logistica",
        "inspecciones": "inspecciones", "disposicion-inventario": "disposicion",
        "reembolsos-costos": "reembolsos", "ventas-catalogos": "ventas",
        "evidencias": "evidencias", "analisis-auditoria": "auditoria",
        "reportes-analitica": "reportes", "causa-raiz": "causa_raiz",
        "sincronizacion": "sincronizacion", "proveedores": "proveedores",
        "integraciones-monitoreo": "integraciones", "clasificacion-motivos": "motivos",
    }
    for servicio, upstream in destinos.items():
        assert f"server {servicio}:8000 resolve;" in NGINX, servicio
        expresion = f"proxy_pass http://{upstream}_backend"
        assert expresion in HTTP, servicio
        assert expresion in TLS, servicio


def test_dns_docker_se_resuelve_dinamicamente():
    assert "resolver 127.0.0.11 valid=5s ipv6=off;" in NGINX
    assert NGINX.count(" resolve;") == len(SERVICIOS)


def test_tls_redirige_y_no_admite_protocolos_obsoletos():
    assert "return 308 https://$host$request_uri" in TLS
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in TLS
    assert "TLSv1.1" not in TLS
