# Atlas Control: preparación real de publicación

Estado: Development. No enviado a certificación; no publicado ni certificado.

## Cambios verificados

- La ficha inglesa guardó categoría `BUSINESS_AND_FINANCE` y una descripción
  que explica cuenta provisionada, cobertura de fuentes, voz/PIN, autorizaciones
  y límites. No se presenta como un juego ni como servicio de emergencia.
- Se prepararon iconos originales locales de 108×108 y 512×512 píxeles. Son
  recursos de marca, no capturas de infraestructura ni datos de clientes.
- Las declaraciones verificables indican datos personales (identificadores
  de cuenta/perfil), ausencia de publicidad y de público infantil. Se declara
  posibilidad de gasto por servicios autorizados, sin Alexa Shopping Actions.
- No se marcó la certificación de cumplimiento de exportación.
- Las fichas y los iconos no conceden acceso técnico ni sustituyen pruebas.

## Frontera de acceso

El gateway comprueba, por defecto, que el `context.System.user.userId` firmado
por Amazon corresponde a la cuenta propietaria provisionada de esta instalación
antes de consultar el backend, vincular otra voz o tramitar decisiones.
Un token OAuth cualquiera no asigna al usuario la instalación de otro cliente.
Una cuenta sin asignación recibe instrucciones de acceso, sin telemetría.

La lectura se permite a la cuenta Amazon de la instalación (incluidos sus
dispositivos/miembros de hogar). Las aprobaciones sensibles mantienen la
comprobación adicional de `personId` exacto y PIN nativo de nivel 400. El nuevo
control de cuenta no sustituye esos factores ni convierte el sistema actual
de propietario único en una plataforma multiempresa.

Si no existe una vinculación canónica, solo un operador puede provisionar
explícitamente una cuenta bootstrap con `ATLAS_DEPLOYMENT_OWNER_USER_ID`.
No se promociona al primer visitante. Si Mongo no permite verificar la cuenta,
se cierra el acceso; Stop/Cancel siguen disponibles. No usar
`ATLAS_DEPLOYMENT_OWNER_GATE=0` en una instalación real o una skill pública:
la excepción existe únicamente para fixtures unitarios aislados.

## Pendiente antes del envío

1. Aprobar y publicar una política específica de Atlas, equivalente en los
   idiomas de distribución. La política corporativa existente describe el
   sitio web público y no debe usarse para aparentar que ya cubre identificadores
   de Alexa, telemetría privada y autorizaciones. El canal público corporativo
   existente es `privacy@innerchispa.us`.
2. Definir y verificar retención/eliminación en los servicios y respaldos
   relacionados. No borrar decisiones consumidas para habilitar reejecuciones.
3. Provisionar un entorno y cuenta de revisión aislados. No entregar al equipo
   de certificación la cuenta, PIN, Telegram o teléfono de producción del dueño.
   Las instrucciones de pruebas deben describir honestamente qué es virtual
   en ese entorno y qué ha sido comprobado físicamente por separado.
4. Completar las pruebas funcionales de ese acceso: idiomas, vinculación,
   Voice ID/PIN, lectura, cancelación, fuentes antiguas, permisos y cierre único
   de solicitudes. La batería unitaria o una simulación no sustituyen esto.
5. El titular revisa la declaración de exportación que exige Amazon; no se
   acepta en su nombre sin autorización concreta. Después se solicita la
   revisión de Amazon. Solo Amazon puede confirmar la certificación.

Los borradores de privacidad y condiciones se prepararon para revisión del
titular, no como documentos legales ya aprobados o URLs definitivas. No se
inventaron dirección, número fiscal, consentimiento de exportación ni credenciales.
