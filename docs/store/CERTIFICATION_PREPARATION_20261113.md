# Atlas Control: preparación real de publicación

Estado: Development. No enviado a certificación; no publicado ni certificado.

## Evidencia posterior a la preparación

PR #113 integrado, código `27a6fd73c6fe427dd6a58c18da83a4fb93462b3f`,
466 pruebas aprobadas y una omitida en checkout aislado de Intel; CI
`43547755248` y GitGuardian aprobados. Se desplegó reiniciando únicamente el
gateway Alexa. La vinculación del propietario, el PIN y la ruta Echo Disco
permanecieron sin cambios. HTTP local del gateway: 200; petición pública sin
firma: 400. Preflight local: cuenta canónica permitida, cuenta ajena denegada.
La prueba negativa de otra cuenta es un test/preflight, no una sesión real
de otro titular de Amazon.

La simulación oficial Amazon de apertura `0a4e4fea-c344-46c1-a010-0e3fc5db7e19`
terminó `SUCCESSFUL` y recibió el saludo de Atlas después del despliegue,
sin consultar el backend ni ejecutar acciones. No es una nueva prueba física
del PIN; la prueba física de enrollment del 12 de noviembre sigue documentada
por separado.

SMAPI aceptó y terminó la actualización de metadatos en Development. Se
guardaron iconos y textos en en-US, es-US, es-MX y es-ES, con imágenes públicas
fijadas al commit de los assets. No se alteraron los permisos de PIN ni se
marcó exportación. El borrador de instrucciones impide afirmar que ya exista
un acceso de revisión aislado.

Se pulsó Run de nuevo en Certification → Validation: **17 → 5 Fixes Required**.
Quedan la declaración de exportación y la URL de privacidad, repetida por los
cuatro idiomas. Esto no significa que el resto de la certificación funcional
o de políticas esté aprobado: sigue pendiente el entorno de revisión y el
texto de privacidad específico. No se enlazó la política corporativa del sitio
web como si ya cubriera la skill.

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
