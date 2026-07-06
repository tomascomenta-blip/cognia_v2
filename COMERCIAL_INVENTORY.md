# INVENTARIO DE FEATURES — Cognia (versión comercial)

Catálogo sintetizado: **568 features** en 10 áreas. Columnas: feature | entry_point | model_dep (sí = pasa por el 3B/LLM, cuello serial) | packaged (sí = viaja en el wheel `pip install cognia-ai`) | cómo invocar | riesgo.

---

## Área 1 — cli-commands (222 features)

Nota: **todas** son `packaged=sí` salvo `repl_update` y `repl_distill` (dependen de `scripts/`, excluido del wheel). Subcomandos del entry-point (`main_*`) y comandos REPL (`repl_*`).

### 1a. Subcomandos del entry-point (12)

| feature | entry_point | model_dep | packaged | invocar | riesgo |
|---|---|---|---|---|---|
| main_no_args (wizard+REPL) | `cognia/__main__.py:main` | sí | sí | `cognia` | — |
| main_init | `_cmd_init` | no | sí | `cognia init` | — |
| main_install_weights | `_cmd_install_weights` | no | sí | `cognia install-weights --standalone` | descarga red |
| main_download_weights_alias | `main` | no | sí | `cognia download-weights` | — |
| main_server (FastAPI :8000) | `_cmd_server` | sí | sí | `cognia server` | — |
| main_node (swarm) | `_cmd_node` | sí | sí | `cognia node` | swarm online |
| main_coordinator (:8001) | `_cmd_coordinator` | no | sí | `cognia coordinator` | swarm online |
| main_modo | `_cmd_modo` | no | sí | `cognia modo local` | — |
| main_status | `_cmd_status` | no | sí | `cognia status` | — |
| main_leave | `_cmd_leave` | no | sí | `cognia leave` | — |
| main_help | `main` | no | sí | `cognia help` | — |
| main_unknown | `main` (else) | no | sí | `cognia xxx` | — |

### 1b. Comandos REPL cero-LLM (no model-dependent)

| feature | entry_point | packaged | invocar | riesgo |
|---|---|---|---|---|
| repl_limpiar | `_slash_limpiar` | sí | `/limpiar` | — |
| repl_compactar | `_slash_compactar` | sí | `/compactar` | — |
| repl_memoria | `ai.introspect` | sí | `/memoria` | — |
| repl_modulos | `_slash_modulos` | sí | `/modulos` | — |
| repl_exportar_stats | `_slash_exportar_stats` | sí | `/exportar-stats` | — |
| repl_exportar | `_slash_exportar` | sí | `/exportar json f.json` | — |
| repl_costo | `_slash_costo` | sí | `/costo` | — |
| repl_stats | `_slash_stats` | sí | `/stats` | — |
| repl_logros | `_slash_logros` | sí | `/logros` | — |
| repl_patrones | `_slash_patrones` | sí | `/patrones` | — |
| repl_debug | `_slash_debug` | sí | `/debug` | — |
| repl_modo_rapido | `_slash_modo_rapido` | sí | `/modo rapido` | — |
| repl_tema | `_slash_tema` | sí | `/tema oscuro` | — |
| repl_color | `_slash_color` | sí | `/color cyan` | — |
| repl_memoria_limite | `_slash_memoria_limite` | sí | `/memoria-limite 500` | — |
| repl_salir | `cli.py` | sí | `/salir` | — |
| repl_doctor | `cognia.doctor.run_all` | sí | `/doctor` | — |
| repl_update | `scripts/cognia_update.py` | **no** | `/update` | **no empaquetado**: en pip solo imprime pip install -U |
| repl_distill | `scripts/distill.py` | **no** | `/distill` | **no empaquetado**; además model-dep |
| repl_ayuda | `_slash_ayuda_detallada` | sí | `/ayuda` | — |
| repl_reporte | `_slash_reporte` | sí | `/reporte` | — |
| repl_reporte_json | `_slash_reporte_json` | sí | `/reporte-json` | — |
| repl_reporte_completo | `_slash_reporte_completo` | sí | `/reporte-completo` | — |
| repl_reporte_semanal | `_slash_reporte_semanal` | sí | `/reporte-semanal` | — |
| repl_cadena_causal | `_slash_cadena_causal` | sí | `/cadena-causal <e>` | — |
| repl_metas_pendientes | `_slash_metas_pendientes` | sí | `/metas-pendientes` | — |
| repl_yo | `_slash_yo_perfil` | sí | `/yo` | — |
| repl_yo_actualizar | `_slash_yo_actualizar` | sí | `/yo-actualizar` | — |
| repl_yo_introspect | `ai.introspect` | sí | `/yo-introspect` | — |
| repl_conceptos | `ai.list_concepts` | sí | `/conceptos` | — |
| repl_olvido | `ai.forget_cycle` | sí | `/olvido` | — |
| repl_repasar | `ai.review_due/mark_review` | sí | `/repasar` | — |
| repl_contradicciones | `ai.show_contradictions` | sí | `/contradicciones` | — |
| repl_objetivos | `ai.show_goals` | sí | `/objetivos` | — |
| repl_research | `research_engine.show_history` | sí | `/research` | requiere HAS_RESEARCH_ENGINE |
| repl_programs | `program_creator.show_library` | sí | `/programs` | — |
| repl_program_stats | `program_creator.get_session_stats` | sí | `/program_stats` | — |
| repl_aprender | `_slash_aprender_card` | sí | `/aprender f\|r\|t` | — |
| repl_encolar | `program_creator.add_custom_idea` | sí | `/encolar <idea>` | — |
| repl_corregir | `ai.correct` | sí | `/corregir a\|b\|c` | — |
| repl_grafo | `ai.show_graph` | sí | `/grafo Python` | — |
| repl_hecho | `ai.add_fact` | sí | `/hecho s\|p\|o` | — |
| repl_mesh_iniciar | `ai.start_mesh` | sí | `/mesh_iniciar` | abre red P2P |
| repl_mesh_peer | `ai.connect_mesh_peer` | sí | `/mesh_peer host:port` | red P2P |
| repl_mesh_publicar | `ai.publish_knowledge` | sí | `/mesh_publicar s\|p\|o` | red P2P |
| repl_mesh_estado | `ai.mesh_status` | sí | `/mesh_estado` | — |
| repl_seguridad | `ai.security_status` | sí | `/seguridad` | — |
| repl_bloquear | `ai.lock_security` | sí | `/bloquear` | — |
| repl_desbloquear | `ai.unlock_security` | sí | `/desbloquear <pass>` | — |
| repl_escalar | `scale_manager` | sí | `/escalar` | — |
| repl_usuarios | `user_profile.get_profile_manager` | sí | `/usuarios` | — |
| repl_usuario | `ProfileManager.load/save` | sí | `/usuario tomas` | — |
| repl_estilo_info | `learning.style_engine` | sí | `/estilo_info` | — |
| repl_indice_personal | `memory.personal_index` | sí | `/indice_personal` | — |
| repl_indice_add | `PersonalIndex.add` | sí | `/indice_add <c>` | — |
| repl_leer | `ingest.ingest_file` | sí | `/leer doc.pdf` | PDF requiere extra `[pdf]` |
| repl_proyecto | `ingest.ingest_directory` | sí | `/proyecto ./repo` | — |
| repl_listar | `cli.py` | sí | `/listar ./src` | — |
| repl_buscar | `cli.py` | sí | `/buscar regex .` | — |
| repl_escribir | `cli.py` | sí | `/escribir f.txt <c>` | escribe en cwd |
| repl_editar | `cli.py` | sí | `/editar f.txt a\|b` | escribe en cwd |
| repl_ejecutar | `cli.py` | sí | `/ejecutar dir` | shell con blocklist best-effort |
| repl_skills | `_slash_skills` | sí | `/skills` | — |
| repl_modo_ui | `simple_mode.set_ui_mode` | sí | `/modo sencillo` | — |
| repl_agente | `agent.agent_status` | sí | `/agente estado` | — |
| repl_plan_ver | `_slash_plan_ver` | sí | `/plan-ver` | — |
| repl_plan_ok | `_slash_plan_ok` | sí | `/plan-ok p1 2` | — |
| repl_plan_borrar | `_slash_plan_borrar` | sí | `/plan-borrar p1` | — |
| repl_templates | `_slash_templates` | sí | `/templates` | — |
| repl_template_guia | `_slash_template_guia` | sí | `/template-guia <id>` | — |
| repl_meta | `_slash_meta` | sí | `/meta <t>` | — |
| repl_metas | `_slash_metas` | sí | `/metas` | — |
| repl_meta_ok | `_slash_meta_ok` | sí | `/meta-ok m3` | — |
| repl_meta_prog | `_slash_meta_prog` | sí | `/meta-prog m3 50` | — |
| repl_meta_borrar | `_slash_meta_borrar` | sí | `/meta-borrar m3` | — |
| repl_meta_prioridad | `_slash_meta_prioridad` | sí | `/meta-prioridad m3 alta` | — |
| repl_metas_alta | `_slash_metas_alta` | sí | `/metas-alta` | — |
| repl_metas_ordenar | `_slash_metas_ordenar` | sí | `/metas-ordenar` | — |
| repl_proyectos | `memory.project_memory` | sí | `/proyectos` | — |
| repl_historial | `cli.py` | sí | `/historial` | — |
| repl_sesiones | `_slash_sesiones` | sí | `/sesiones` | — |
| repl_resume | `_slash_resume` | sí | `/resume <id>` | — |
| repl_buscar_historial | `_slash_buscar_historial` | sí | `/buscar-historial x` | — |
| repl_sesion_ver | `_slash_sesion_ver` | sí | `/sesion-ver <id>` | — |
| repl_historial_limpiar | `_slash_historial_limpiar` | sí | `/historial-limpiar` | borra historial |
| repl_revisar_sm2 | `_slash_revisar_sm2` | sí | `/revisar` | — |
| repl_memoria_stats | `cli.py` | sí | `/memoria-stats` | — |
| repl_monitor | `cli.py` | sí | `/monitor <cmd>` | ejecuta shell |
| repl_powershell | `cli.py` | sí | `/powershell <cmd>` | ejecuta PS |
| repl_tarea_crear | `cli.py` | sí | `/tarea-crear <t>` | — |
| repl_tarea_lista | `cli.py` | sí | `/tarea-lista` | — |
| repl_tarea_ok | `cli.py` | sí | `/tarea-ok 1` | — |
| repl_tarea_borrar | `cli.py` | sí | `/tarea-borrar 1` | — |
| repl_web_fetch | `cli.py` | no | sí `/web-fetch <url>` | **requiere red** |
| repl_buscar_kg | `cli.py` | sí | `/buscar-kg Python` | — |
| repl_kg_agregar | `cli.py` | sí | `/kg-agregar s\|p\|o` | — |
| repl_kg_stats | `cli.py` | sí | `/kg-stats` | — |
| repl_kg_predicados | `cli.py` | sí | `/kg-predicados` | — |
| repl_kg_exportar | `cli.py` | sí | `/kg-exportar kg.json` | — |
| repl_kg_camino | `cli.py` | sí | `/kg-camino a\|b` | — |
| repl_worktree | `cli.py` | sí | `/worktree feat-x` | requiere git |
| repl_notificar | `cli.py` | sí | `/notificar <msg>` | — |
| repl_notif | `_slash_notif` | sí | `/notif` | — |
| repl_notif_todas | `_slash_notif_todas` | sí | `/notif-todas` | — |
| repl_notif_leer | `_slash_notif_leer` | sí | `/notif-leer <id>` | — |
| repl_notif_limpiar | `_slash_notif_limpiar` | sí | `/notif-limpiar` | — |
| repl_recordar | `_slash_recordar` | sí | `/recordar <x>` | — |
| repl_recordatorios | `_slash_recordatorios` | sí | `/recordatorios` | — |
| repl_recordar_cancelar | `_slash_recordar_cancelar` | sí | `/recordar-cancelar <id>` | — |
| repl_resumen_sesion | `_slash_resumen_sesion_full` | sí | `/resumen-sesion` | — |
| repl_config | `cli.py` | sí | `/config <k> <v>` | — |
| repl_esfuerzo | `_active_effort` | sí | `/esfuerzo alto` | — |
| repl_recap | `cli.py` | sí | `/recap` | — |
| repl_feedback_sesion | `cli.py` | sí | `/feedback-sesion` | — |
| repl_feedback | `cli.py` | sí | `/feedback <x>` | — |
| repl_notas_buscar | `cli.py` | sí | `/notas-buscar x` | — |
| repl_notas_stats | `cli.py` | sí | `/notas-stats` | — |
| repl_notas | `cli.py` | sí | `/notas` | — |
| repl_nota_agregar | `cli.py` | sí | `/nota-agregar x` | — |
| repl_nota_fijar | `cli.py` | sí | `/nota-fijar <id>` | — |
| repl_aprendiendo | `cli.py` | sí | `/aprendiendo` | — |
| repl_aprendiendo_buscar | `cli.py` | sí | `/aprendiendo-buscar x` | — |
| repl_backup | `cli.py` | sí | `/backup` | — |
| repl_mi_uso | `cli.py` | sí | `/mi-uso` | — |
| repl_mi_uso_detalle | `cli.py` | sí | `/mi-uso-detalle` | — |
| repl_buscar_memoria | `cli.py` | sí | `/buscar-memoria x` | — |
| repl_contexto_semantico | `cli.py` | sí | `/contexto-semantico` | — |
| repl_temas | `cli.py` | sí | `/temas` | — |
| repl_mi_cognia | `cli.py` | sí | `/mi-cognia` | — |
| repl_perfil_completo | `cli.py` | sí | `/perfil-completo` | — |
| repl_estado | `cli.py` | sí | `/estado` | — |
| repl_ver_criticas | `cli.py` | sí | `/ver-criticas` | — |
| repl_mapa | `cli.py` | sí | `/mapa` | — |
| repl_features | `cli.py` | sí | `/features` | — |
| repl_vocabulario_guardar | `cli.py` | sí | `/vocabulario-guardar x` | — |
| repl_vocabulario | `cli.py` | sí | `/vocabulario` | — |
| repl_hechos_solidos | `cli.py` | sí | `/hechos-solidos` | — |
| repl_conocimiento_ver | `cli.py` | sí | `/conocimiento-ver x` | — |
| repl_quiz_stats | `cli.py` | sí | `/quiz-stats` | — |
| repl_exportar_todo | `cli.py` | sí | `/exportar-todo b.json` | — |
| repl_camino_nuevo | `cli.py` | sí | `/camino-nuevo x` | — |
| repl_caminos | `cli.py` | sí | `/caminos` | — |
| repl_camino_avanzar | `cli.py` | sí | `/camino-avanzar <id>` | — |
| repl_etiquetar | `cli.py` | sí | `/etiquetar x` | — |
| repl_cognia_sabe | `cli.py` | sí | `/cognia-sabe` | — |
| repl_cognia_aprende | `cli.py` | sí | `/cognia-aprende x` | — |
| repl_cognia_olvida | `cli.py` | sí | `/cognia-olvida x` | — |
| repl_conflictos_kg | `cli.py` | sí | `/conflictos-kg` | — |
| repl_verificar_kg | `cli.py` | sí | `/verificar-kg` | — |
| repl_resolver_conflicto | `cli.py` | sí | `/resolver-conflicto <id>` | — |
| repl_comandos | `cli.py` | sí | `/comandos` | — |
| repl_digest | `cli.py` | sí | `/digest` | — |
| repl_cognia_info | `cli.py` | sí | `/cognia-info` | — |
| repl_inicio_dia | `cli.py` | sí | `/inicio-dia` | — |
| repl_contexto | `_slash_ver_contexto` | sí | `/contexto` | — |
| repl_contexto_mapa | `cli.py` | sí | `/contexto-mapa` | — |
| repl_contexto_stats | `cli.py` | sí | `/contexto-stats` | — |
| repl_contexto_auto | `cli.py` | sí | `/contexto-auto on` | — |
| repl_ver_contexto | `_slash_ver_contexto` | sí | `/ver-contexto` | — |
| repl_limpiar_sesion | `_slash_limpiar_sesion` | sí | `/limpiar-sesion` | — |
| repl_unknown_slash | `cli.py` catch-all | sí | `/xxx` | — |

### 1c. Comandos REPL model-dependent (pasan por el 3B — cuello serial)

| feature | entry_point | packaged | invocar | riesgo |
|---|---|---|---|---|
| repl_sugerir | `_slash_sugerir` | sí | `/sugerir` | — |
| repl_dormir | `ai._sleep_sync` | sí | `/dormir` | — |
| repl_investigar | `ai.github_research` | sí | `/investigar x` | requiere red |
| repl_razonar | `ai.investigate` | sí | `/razonar x` | — |
| repl_aprende_repo | `_slash_aprende_repo` | sí | `/aprende-repo <url>` | requiere red |
| repl_crear | `ai.create_program` | sí | `/crear <idea>` | — |
| repl_observar | `ai.process` | sí | `/observar x` | — |
| repl_hipotesis | `ai.generate_hypothesis` | sí | `/hipotesis x` | — |
| repl_experimento | `ai.run_experiment` | sí | `/experimento x` | — |
| repl_evaluar_idea | `ai.evaluate_idea` | sí | `/evaluar-idea x` | — |
| repl_analogia | `ai.find_analogies` | sí | `/analogia x` | — |
| repl_abstraer | `ai.solve_by_abstraction` | sí | `/abstraer x` | — |
| repl_transferir | `ai.transfer_principle` | sí | `/transferir a\|b` | — |
| repl_diversidad | `ai.measure_diversity` | sí | `/diversidad a\|\|b` | — |
| repl_explorar | `ai.explore_problem` | sí | `/explorar x` | — |
| repl_explicar | `ai.explain` | sí | `/explicar x` | — |
| repl_predecir | `ai.predict_next` | sí | `/predecir x` | — |
| repl_inferir | `ai.infer_about` | sí | `/inferir x` | — |
| repl_narrativa | `ai.get_narrative` | sí | `/narrativa x` | — |
| repl_diff | `orchestrator.infer` | sí | `/diff f.py` | — |
| repl_skill_nuevo | `_slash_skill_nuevo` | sí | `/skill-nuevo x` | — |
| repl_skill_cargar | `_slash_skill_cargar` | sí | `/skill-cargar x` | — |
| repl_skill | `_slash_skill` | sí | `/skill` | — |
| repl_hacer (**agente**) | `_run_agent_task` | sí | `/hacer <tarea>` | punto de entrada agente |
| repl_largo | `_slash_largo` | sí | `/largo <x>` | — |
| repl_modelo | `_slash_modelo` | sí | `/modelo 7b` | — |
| repl_plan_crear | `_slash_plan_crear` | sí | `/plan <obj>` | — |
| repl_template | `_slash_template` | sí | `/template <id>` | — |
| repl_pensar | `orchestrator.infer` | sí | `/pensar x` | — |
| repl_deliberar | `reasoning.cognitive_loop` | sí | `/deliberar x` | — |
| repl_flujo | `agents.flow.run_flow` | sí | `/flujo x` | — |
| repl_resumir | `orchestrator.infer` | sí | `/resumir` | — |
| repl_revisar_archivo | `cli.py` | sí | `/revisar f.py` | — |
| repl_web_buscar | `cli.py` | sí | `/web-buscar x` | requiere red |
| repl_buscar_web | `cli.py` | sí | `/buscar-web x` | requiere red |
| repl_kg_inferir | `cli.py` | sí | `/kg-inferir x` | — |
| repl_kg_relacionar | `cli.py` | sí | `/kg-relacionar a\|b` | — |
| repl_kg_responder | `cli.py` | sí | `/kg-responder x` | — |
| repl_debate | `cli.py` | sí | `/debate x` | — |
| repl_sintetizar | `cli.py` | sí | `/sintetizar x` | — |
| repl_y_si | `cli.py` | sí | `/y-si x` | — |
| repl_reflexion_profunda | `cli.py` | sí | `/reflexion-profunda` | — |
| repl_calidad_respuestas | `cli.py` | sí | `/calidad-respuestas` | — |
| repl_recomendar | `cli.py` | sí | `/recomendar` | — |
| repl_proximos_pasos | `cli.py` | sí | `/proximos-pasos` | — |
| repl_cristalizar | `cli.py` | sí | `/cristalizar` | — |
| repl_quiz | `cli.py` | sí | `/quiz x` | — |
| repl_argumento | `cli.py` | sí | `/argumento x` | — |
| repl_chat_libre (**chat**) | `cli.py` else-branch | sí | texto libre | auto-enruta a /hacer por intent |

---

## Área 2 — agent-loop-tools (54 features)

Todas `packaged=sí` salvo `lcd_tool_loading` (no).

### 2a. Tools cero-LLM del registro

| feature | entry_point | model_dep | packaged | invocar | riesgo |
|---|---|---|---|---|---|
| tool_registry_core | `agent/tools.py:TOOLS` | no | sí | `run_tool('fecha','',{})` | — |
| tool_leer_archivo | `_leer_archivo` | no | sí | `ACCION: leer_archivo f` | — |
| tool_escribir_archivo | `_escribir_archivo` | no | sí | `ACCION: escribir_archivo out/f\|c` | confinado a workspace |
| tool_apendar_archivo | `_apendar_archivo` | no | sí | `ACCION: apendar_archivo f\|c` | — |
| tool_copiar_archivo | `_copiar_archivo` | no | sí | `ACCION: copiar_archivo a\|b` | — |
| tool_listar | `_listar` | no | sí | `ACCION: listar dir` | — |
| tool_arbol | `_arbol` | no | sí | `ACCION: arbol dir` | — |
| tool_contar_lineas | `_contar_lineas` | no | sí | `ACCION: contar_lineas f` | — |
| tool_buscar | `_buscar` | no | sí | `ACCION: buscar pat\|dir` | depende de rg en PATH |
| tool_ejecutar | `_ejecutar` | no | sí | `ACCION: ejecutar echo` | **shell=True, blocklist best-effort, no sandbox** |
| tool_tests | `_tests` | no | sí | `ACCION: tests tests/x.py` | — |
| tool_py_validar | `_py_validar` | no | sí | `ACCION: py_validar f.py` | — |
| tool_json_validar | `_json_validar` | no | sí | `ACCION: json_validar f.json` | — |
| tool_git_estado | `_git_estado` | no | sí | `ACCION: git_estado` | — |
| tool_git_diff | `_git_diff` | no | sí | `ACCION: git_diff f` | — |
| tool_git_log | `_git_log` | no | sí | `ACCION: git_log` | — |
| tool_calcular | `_calcular` (ast) | no | sí | `ACCION: calcular 2**10` | — |
| tool_fecha | `_fecha` | no | sí | `ACCION: fecha` | — |
| tool_http_get | `_http_get` | no | sí | `ACCION: http_get <url>` | **sin allowlist de dominios**; requiere red |
| tool_recordar | `_recordar` (RAG) | no | sí | `ACCION: recordar x` | depende de memoria previa |
| tool_memorizar | `_memorizar` | no | sí | `ACCION: memorizar x` | — |
| tool_kg_buscar | `_kg_buscar` | no | sí | `ACCION: kg_buscar Python` | — |
| tool_kg_agregar | `_kg_agregar` | no | sí | `ACCION: kg_agregar s\|r\|o` | — |
| tool_anotar | `_anotar` | no | sí | `ACCION: anotar k\|v` | — |
| tool_notas | `_notas` | no | sí | `ACCION: notas` | — |
| tool_responder (cierre) | `cli.py:_run_agent_task` | no | sí | `ACCION: responder x` | — |
| role_scoped_tools | `ROLE_TOOLS` | no | sí | vía `_allowed_tools` | — |
| tool_usage_counters | `_record_usage` | no | sí | `get_tool_usage()` | — |

### 2b. Tools y andamiaje model-dependent

| feature | entry_point | packaged | invocar | riesgo |
|---|---|---|---|---|
| tool_resumir | `_resumir` | sí | `ACCION: resumir <texto>` | requiere backend |
| tool_generar_codigo (BoN+juez) | `_generar_codigo` / `candidates.py` | sí | `ACCION: generar_codigo out/x.py\|spec` | — |
| tool_crear_herramienta (HERMES) | `_crear_herramienta` / `tool_synthesis.py` | sí | `ACCION: crear_herramienta n\|p\|in\|out` | **código auto-generado ejecutable sin revisión humana** (mitigado por scan+sandbox) |
| tool_delegar_subtarea | `_delegar_subtarea` | sí | `ACCION: delegar_subtarea rol\|tarea` | — |
| agent_loop_react | `cli.py:_run_agent_task` | sí | `/hacer <tarea>` | — |
| dynamic_step_budget | `loop.py:estimate_step_budget` | sí | interno | — |
| stepwise_bon_gating | `stepwise.py` | no | sí | interno | — |
| generate_then_structure | `structure.py` | sí | interno | — |
| bon_pre_step_shortcircuit | `cli.py` | sí | `/hacer <firma>` | — |
| best_of_n_judge | `candidates.py:best_of_n` | sí | interno | — |
| skill_auto_apply_and_record | `skills.py:find_skill` | sí | `/hacer <match>` | — |
| slash_hacer_command | `cli.py` | sí | `/hacer` | — |
| task_decomposition | `cli.py` | sí | `/hacer <tarea larga>` | — |

### 2c. Andamiaje cero-LLM

| feature | entry_point | packaged | invocar | riesgo |
|---|---|---|---|---|
| objective_context_window | `loop.py:objective_context` | sí | interno | — |
| first_action_block_parser | `loop.py:first_action_block` | sí | interno | — |
| stuck_detector | `loop.py:register_action` | sí | interno | — |
| goal_contract_verification | `agents/goal_contract.py` | sí | interno tras /hacer | — |
| skill_capture_l2 | `skill_capture.py` | sí | interno | — |
| fewshot_injection | `fewshot.py` | sí | interno | — |
| prompt_evolution_live_guidance | `prompt_evolution.py:live_guidance` | sí | interno | — |
| simple_mode_tool_filter | `simple_mode.py` | sí | interno | — |
| lcd_tool_loading | `cognia_x.lcd.*` | **no** | repo-fuente | **GAP repo↔pip: desaparece en pip install** |
| generated_tools_hot_load | `tool_synthesis.py` | sí | interno | dir generated_tools no en package-data; arranca vacío en pip |
| intent_auto_routing | `intent.py:detect` | sí | texto libre | — |
| agent_state_persistence | `cli.py` (~/.cognia_agent_state.json) | sí | interno | — |
| write_path_sandboxing | `workers/dev_tools.py:resolve_write_path` | sí | interno | — |

---

## Área 3 — rsi-autoprompt (18 features)

Todas `packaged=sí`.

| feature | entry_point | model_dep | invocar | riesgo |
|---|---|---|---|---|
| prompt_evolution.evolve | `prompt_evolution.py:evolve` | sí | `run_prompt_evolution --smoke` | — |
| score_scaffold | `:score_scaffold` | sí | interno | — |
| bootstrap_exemplars/make_bootstrapped | `:bootstrap_exemplars` | sí | interno | — |
| mcnemar | `:mcnemar` | no | interno | — |
| persist_best/load_best | `:persist_best` | no | interno | — |
| live_guidance (puente a /hacer) | `:live_guidance` | no | interno | — |
| mutation_operators | `:propose_mutations` | no | interno | — |
| tool_synthesis.crear_herramienta (HERMES) | `tool_synthesis.py:synthesize_and_register` | sí | `ACCION: crear_herramienta ...` | RCE mitigado por scan AST + sandbox |
| verify_tool (oráculo duro) | `:verify_tool` | no | `verify_tool(code,in,out)` | — |
| tier lifecycle (staged/verified/retired) | `:record_tool_use` | no | interno | — |
| handle_live_failure (repair-on-live) | `:handle_live_failure` | sí | interno | — |
| load_generated_tools/synth_note | `:load_generated_tools` | no | interno | — |
| skills.load_skills/find_skill (semántico) | `skills.py:find_skill` | no | `find_skill(x)` | — |
| record_skill_use (decay) | `skills.py:record_skill_use` | no | interno | escribe sidecar .skill_usage.json |
| persist_skill (nivel-2, blocklist+dedupe) | `skills.py:persist_skill` | no | interno | — |
| skill_capture.maybe_capture_skill | `skill_capture.py` | no | interno tras /hacer | — |
| fewshot.fewshot_for | `fewshot.py` | no | interno | — |
| adaptive_prompt.learn_user_traits/build | `adaptive_prompt.py` | no | interno cada turno | — |

---

## Área 4 — memory (42 features)

Todas `packaged=sí`.

| feature | entry_point | model_dep | invocar | riesgo |
|---|---|---|---|---|
| episodic_store | `memory/episodic.py:store` | no | `EpisodicMemory.store(...)` | — |
| episodic_retrieve_similar | `:retrieve_similar` | no | `.retrieve_similar(v,5)` | — |
| episodic_review_scheduling | `:get_due_for_review` | no | `.get_due_for_review()` | — |
| episodic_window_count | `:get_in_window/count` | no | `.count()` | — |
| vector_cache | `episodic_fast.py:VectorCache` | no | `get_vector_cache(db)` | — |
| working_memory_buffer | `working.py:WorkingMemory` | no | `WorkingMemory()` | — |
| perception_encode | `working.py:PerceptionModule` | no | `.extract_features(t)` | — |
| semantic_concept_store | `semantic.py:update_concept` | no | `.update_concept(...)` | — |
| semantic_spreading_activation | `:spreading_activation` | no | `.spreading_activation(c,2)` | — |
| semantic_find_related_crystallized | `:get_crystallized` | no | `.get_crystallized(...)` | — |
| semantic_search_tfidf | `semantic_search.py:search` | no | `.search('python')` | — |
| knowledge_graph_add_triple | `knowledge/graph.py:add_triple` | no | `kg.add_triple(...)` | — |
| knowledge_graph_query | `:get_facts/stats` | no | `kg.get_facts(c)` | — |
| knowledge_graph_networkx_path | `:graph_path` | no | `kg.graph_path(a,b)` | requiere networkx |
| knowledge_graph_auto_extract | `:extract_and_store` | no | `kg.extract_and_store(t)` | regex ES/EN |
| knowledge_graph_auto_facts_audit | `:get_auto_facts_count` | no | `kg.get_recent_auto_facts()` | — |
| hierarchical_memory_write | `hierarchical.py:write` | no | `HierarchicalMemory.write(...)` | — |
| hierarchical_memory_recall/consol/decay | `:recall/consolidate/decay` | no | `hm.recall(x,5)` | — |
| forgetting_decay_cycle | `forgetting.py:decay_cycle` | no | `f.decay_cycle()` | — |
| consolidation_sleep | `forgetting.py:sleep_consolidation` | no | `c.sleep_consolidation()` | — |
| memory_compressor_cluster_merge | `memory_compressor.py:compress` | no | `mc.compress()` | requiere instancia Cognia |
| memory_budget_enforce | `memory_budget.py:enforce` | no | `enforce_memory_budget(db)` | — |
| memoria_limite_cli | `cli.py` /memoria-limite | no | `/memoria-limite 500 50` | — |
| long_term_consolidator | `long_term_consolidator.py` | no | `lc.consolidate('default')` | — |
| narrative_thread | `narrative.py:build_thread` | no | `nt.build_thread(1)` | — |
| personal_index | `personal_index.py` | no | `pi.search('x')` | — |
| project_memory_flow | `project_memory.py` | no | `pm.start_flow(...)` | — |
| recap_policy | `recap_policy.py:should_recap` | no | `should_recap(...)` | — |
| reranker | `reranker.py:rerank` | no | `rerank(...)` | — |
| chat_history | `chat.py:ChatHistory` | no | `ch.get_recent(10)` | — |
| chat_history_cli | `cli.py` /historial | no | `/historial` | — |
| user_profile_kv | `chat.py:UserProfile` | no | `up.set(k,v)` | — |
| perfil_completo_cli | `cli.py` /perfil-completo | no | `/perfil-completo` | — |
| emotion_wheel | `emotion_wheel.py:process` | no | `ew.process(24)` | — |
| adapter_store | `adapter_store.py` | no | `store.put(uid,adp)` | LoRA solamente |
| memoria_stats_cli | `cli.py` /memoria-stats | no | `/memoria-stats` | — |
| memoria_estado_cli | `cli.py` /memoria | no | `/memoria` | — |
| cognitive_fatigue_monitor | `fatiga_cognitiva.py` | no | `get_fatigue_monitor()` | — |
| fatiga_cognitiva_wiring | `cognia.py:self.fatigue` | no | interno | — |
| curiosity_engine_queue | `reasoning/curiosity_engine.py` | no | `ce.enqueue(...)` | — |
| curiosity_queue_processing | `:get_pending/mark_answered` | sí | `ce.get_pending(5)` | LLM entra al resolver |
| active_curiosity_engine_wiring | `cognia.py:self.curiosity_engine` | sí | interno | requiere 3B para confidence |

---

## Área 5 — image-lcd-beta / creador de imágenes-escenas (33 features)

**TODA el área es `packaged=no`** (cognia_x excluido del wheel; ver hallazgo bloqueante abajo). Todas cero-LLM salvo `escena_crear` (fallback opcional 3B) y el harness de motor.

| feature | entry_point | model_dep | invocar | riesgo |
|---|---|---|---|---|
| **packaging-status** (meta) | `pyproject.toml exclude` + `cli.py:7284` | no | Read pyproject | **BLOQUEANTE para venta: código muerto en pip actual** |
| escena_crear | `tools_lcd.py:_escena_crear` | no (fallback 3B) | `ACCION: escena_crear <desc>` | — |
| escena_editar | `_escena_editar` | no | `ACCION: escena_editar obj\|prop` | — |
| escena_consultar | `_escena_consultar` | no | `ACCION: escena_consultar obj` | — |
| render_aprox | `renderer.py:render_to` | no | `ACCION: render_aprox f.png` | depende de Pillow |
| atribuir_fallo (oráculo) | `arbiter.py:attribute_scene_failure` | no | `ACCION: atribuir_fallo` | — |
| reejecutar_etapa | `_reejecutar_etapa` | no | `ACCION: reejecutar_etapa plan` | — |
| escena_agregar | `_escena_agregar` | no | `ACCION: escena_agregar obj\|...` | — |
| escena_quitar | `_escena_quitar` | no | `ACCION: escena_quitar obj` | — |
| escena_duplicar | `scene.py:duplicate` | no | `ACCION: escena_duplicar obj\|dx dy` | — |
| escena_mover | `_escena_mover` | no | `ACCION: escena_mover obj\|x y` | — |
| escena_rotar_escalar_capa | `_escena_rotar/_escalar/_capa` | no | `ACCION: escena_rotar obj\|45` | — |
| escena_material | `_escena_material` | no | `ACCION: escena_material obj\|m` | — |
| escena_camara_luz_fondo | `_escena_camara/_luz/_fondo` | no | `ACCION: escena_fondo \|azul` | — |
| escena_alinear_distribuir | `_escena_alinear/_distribuir` | no | `ACCION: escena_alinear a,b\|left` | — |
| escena_relacionar | `_escena_relacionar` | no | `ACCION: escena_relacionar a\|rel\|b` | — |
| escena_fisica | `physics.py:settle` | no | `ACCION: escena_fisica` | — |
| escena_forma | `_escena_forma` | no | `ACCION: escena_forma obj\|tri` | — |
| escena_vertices | `_escena_vertices` | no | `ACCION: escena_vertices obj\|...` | — |
| escena_biselar (Bevel) | `modeling.py:bevel` | no | `ACCION: escena_biselar obj\|0.15` | — |
| escena_subdividir | `modeling.py:subdivide` | no | `ACCION: escena_subdividir obj\|2` | — |
| escena_suavizar (Subsurf) | `modeling.py:smooth` | no | `ACCION: escena_suavizar obj\|1` | — |
| escena_insertar (Inset) | `modeling.py:inset` | no | `ACCION: escena_insertar obj\|0.3` | — |
| escena_extruir (Extrude) | `modeling.py:extrude_edge` | no | `ACCION: escena_extruir obj\|...` | — |
| escena_espejar (Mirror) | `modeling.py:mirror` | no | `ACCION: escena_espejar obj\|x` | — |
| escena_array | `modeling.py:array` | no | `ACCION: escena_array obj\|5 ...` | — |
| escena_poligono (ngon) | `modeling.py:ngon` | no | `ACCION: escena_poligono obj\|6` | — |
| escena_animar_caida (GIF) | `animation.py:render_fall_gif` | no | `ACCION: escena_animar_caida f.gif` | tarda varios s, sin timeout propio |
| escena_exportar (SVG/JSON) | `exporters.py` | no | `ACCION: escena_exportar json\|f` | — |
| escena_importar | `exporters.py:import_scene_json` | no | `ACCION: escena_importar f.json` | — |
| escena_deshacer_rehacer | `history.py:SceneHistory` | no | `ACCION: escena_deshacer` | — |
| escena_plantilla (6 templates) | `templates.py:get_template` | no | `ACCION: escena_plantilla mesa_servida` | — |
| motor_interno_y_harnesses (verif E2E) | `lcd/{scene,renderer,physics,planner,arbiter,eval,e2e_agente_escena}.py` | sí | `python -m cognia_x.lcd.e2e_agente_escena` | eval_llm_planner/eval_selfplay requieren 3B vivo |

---

## Área 6 — model-backend (46 features)

Todas `packaged=sí` salvo `llama_server_backend` (no — el binario `node/llama-server.exe` no viaja en el wheel).

| feature | entry_point | model_dep | packaged | invocar | riesgo |
|---|---|---|---|---|---|
| orchestrator_local_init | `orchestrator.py:__init__` | no | sí | `ShatteringOrchestrator(...)` | — |
| infer_sync (API principal) | `:infer` | sí | sí | `o.infer(prompt)` | — |
| ainfer_async | `:ainfer` | sí | sí | `await o.ainfer(...)` | — |
| astream_chat | `:astream_chat` | sí | sí | `async for ... astream_chat` | — |
| astream_single_turn | `:astream` | sí | sí | `async for ... astream` | — |
| route_only | `:route_only` | no | sí | `o.route_only(x)` | — |
| shards_ready_probe | `:shards_ready` | no | sí | `o.shards_ready()` | — |
| preload_fragments | `:preload` | no | sí | `o.preload('logos')` | — |
| status_report | `:status` | no | sí | `o.status()` | — |
| decay_precision | `:decay_precision` | no | sí | `o.decay_precision(0.3)` | — |
| lpc_cross_turn_cache | `:LatentPersistenceCache` | no | sí | `lpc_session_id=` | — |
| try_load_llama | `:_try_load_llama` | sí | sí | `o._try_load_llama()` | — |
| reload_llama (hot-swap) | `:reload_llama` | sí | sí | `o.reload_llama()` | — |
| local_infer_dispatch | `:_local_infer` | sí | sí | vía infer | — |
| shard_engine_pipeline (numpy INT4) | `:_shard_infer` | sí | sí | requiere .npz | — |
| shard_infer_stream | `:_shard_infer_stream` | sí | sí | vía astream | — |
| ollama_fallback | `:_ollama_infer` | sí | sí | requiere Ollama | camino online opcional |
| distributed_infer | `:_distributed_infer` | sí | sí | `coordinator_url=` | swarm online |
| llama_backend_facade | `node/llama_backend.py:try_load` | sí | sí | `LlamaBackend.try_load()` | — |
| llama_cpp_python_backend | `:_LlamaCppBackend` | sí | sí | pip install llama-cpp-python | — |
| llama_server_backend | `:_LlamaServerBackend` | sí | **no** | `node/llama-server.exe` | **binario no empaquetado** (pinned b9391) |
| adopt_running_server | `:_check_adopted_server` | sí | sí | server previo en :8088 | — |
| gguf_autodiscovery | `:_find_gguf` | no | sí | `_find_gguf()` | — |
| model_switch_slash_modelo | `cli.py:_slash_modelo` | sí | sí | `/modelo 7b` | — |
| gguf_registry_constants | `model_constants.py:resolve_gguf_path` | no | sí | `resolve_gguf_path('3b')` | — |
| lora_adapter_loading | `:_lora_args` | no | sí | `LLAMA_LORA_PATH=...` | — |
| speculative_decoding_ngram | `:_spec_args` | sí | sí | `COGNIA_SPEC_TYPE=ngram-mod` | draft-* prohibido en CPU |
| sampling_params_passthrough | `:_sampling_payload` | no | sí | `generate(...,top_p=)` | — |
| grammar_constrained_generation | `:generate(grammar=)` | sí | sí | GBNF string | solo camino server |
| stop_reason_mapping | `:_stop_reason` | no | sí | `.last_stop_reason` | — |
| generate_long_autocontinuation | `:generate_long` | sí | sí | `generate_long(...,5000)` | — |
| generate_hierarchical | `:generate_hierarchical` | sí | sí | `generate_hierarchical(...)` | — |
| generate_delegated | `:generate_delegated` | sí | sí | `generate_delegated(...)` | — |
| outline_parser | `:_parse_outline` | no | sí | `_parse_outline(t)` | — |
| append_to_user_turn_fix | `:_append_to_user_turn` | no | sí | interno | fix regresión 2026-07-04 |
| props_endpoint | `:props` | sí | sí | `curl /props` | — |
| backend_stop | `:stop` | no | sí | `backend.stop()` | — |
| model_constants_qwen_llama | `model_constants.py` | no | sí | `QWEN25_CODER_3B` | — |
| npq_shard_precision | `:QWEN_SHARD_PRECISION` | no | sí | constante | — |
| dynamic_precision_promotion | `:DYN_QUANT_THRESH_*` | no | sí | vía decay_precision | — |
| generation_token_budgets | `:GEN_*` | no | sí | `GEN_LONG_MAX_TOKENS` | — |
| router_semantic_constants | `:ROUTER_SEMANTIC_*` | no | sí | `GlobalRouter().route(x)` | — |
| cognia_system_prompt_identity | `:COGNIA_SYSTEM_PROMPT` | sí | sí | preguntar "¿quién te creó?" | — |
| ctx_size_config | `node/llama_backend.py:_CTX_SIZE` | no | sí | `LLAMA_CTX_SIZE=16384` | — |
| server_thread_tuning | `:__init__` (cpu-1) | no | sí | interno | — |
| hf_shards_dataset_constants | `:HF_SHARDS_BASE_URL` | no | sí | constante | — |

---

## Área 7 — online-swarm (24 features) — DESACTIVAR por default

Todas `packaged=sí` salvo `docker_railway_deploy_configs` (no). Ver sección (c) de conclusiones para el detalle de qué apagar.

| feature | entry_point | model_dep | packaged | invocar | riesgo |
|---|---|---|---|---|---|
| default_off_switch | `__main__.py` + `language_engine.py:_get_swarm` | no | sí | unset COGNIA_COORDINATOR_URL | **interruptor implícito por env var, falta flag explícito COGNIA_DISABLE_SWARM** |
| cli_modo_compartido | `_cmd_modo` | no | sí | `cognia modo compartido` | solo guarda preferencia |
| cognia_node_cmd | `node/main.py:main` | no | sí | `cognia node` | requiere coordinador |
| cognia_coordinator_cmd | `coordinator/app.py:app` | no | sí | `cognia coordinator` | — |
| node_register_heartbeat_leave | `coordinator/app.py` + `registry.py` | no | sí | REST /api/node/* | — |
| swarm_status_route_replication | `coordinator/app.py` | no | sí | `/api/swarm/*` | — |
| model_catalog_endpoints | `coordinator/app.py:model_config` | no | sí | `/api/models` | — |
| relay_websocket_pipeline | `coordinator/relay.py` | no | sí | `/ws/relay/{sid}/{shard}` | `/session/infer` sin auth por default; requiere COORDINATOR_KEY |
| shard_engine_real_and_simulation | `node/shard_engine.py` | sí | sí | `ShardEngine(cfg)` | — |
| wire_protocol_encode_decode | `node/shard_engine.py` | no | sí | `encode_text/decode_wire` | — |
| shattering_route_status_infer | `coordinator/app.py` | sí | sí | `/api/shattering/*` | requiere nodos logos/techne/rhetor → 503 |
| contributor_tiers_ledger | `coordinator/contributor.py` | no | sí | `/api/tiers` | capa económica |
| federated_learning_fedavg | `coordinator/federated_store.py` | sí | sí | `/api/federated/*` | **solo adapters LoRA**; DP responsabilidad del cliente, no forzado server-side |
| event_bus_websocket | `coordinator/event_bus.py` | no | sí | `/ws/events` | — |
| sar_shard_availability_redundancy | `coordinator/shard_registry.py` | no | sí | `/api/swarm/replication` | — |
| coordinator_auth_admin_key | `coordinator/app.py:require_admin` | no | sí | `COORDINATOR_KEY=` | sin STRICT_AUTH corre permisivo |
| swarm_client_and_relay_client | `node/client.py` + `relay_client.py` | sí | sí | `SwarmClient(...)` | **SwarmClient parece código muerto (no wireado al CLI)** |
| shard_downloader | `node/downloader.py` | sí | sí | `cognia install-weights` | descarga HF |
| local_adapter_elc_lora | `node/local_adapter.py` | sí | sí | `LoRAWeights.zero_init()` | — |
| inference_pipeline_distributed | `node/inference_pipeline.py` + `language_engine.py:_call_swarm` | sí | sí | `COGNIA_COORDINATOR_URL=` | **punto por el que el swarm PUEDE colarse en generación del engine legacy** |
| mesh_node_p2p_knowledge | `network/mesh_node.py` + `cognia.py:start_mesh` | no | sí | `cognia.start_mesh()` | **singleton SIEMPRE instanciado al iniciar** (pasivo hasta start_mesh) |
| crdt_knowledge_graph | `network/crdt_graph.py` | no | sí | `CRDTKnowledgeGraph(n)` | — |
| privacy_layer_differential_privacy | `network/privacy.py` | no | sí | `privatize_embedding(...)` | — |
| docker_railway_deploy_configs | `Dockerfile.coordinator/railway.toml` | no | **no** | `docker compose up coordinator` | infra, no viaja en pip pero sí en GitHub |

---

## Área 8 — storage-security (23 features)

Todas `packaged=sí` salvo `migrate_db_encrypt` (no — vive en `scripts/`). Todas cero-LLM.

| feature | entry_point | packaged | invocar | riesgo |
|---|---|---|---|---|
| db_pool.SQLitePool | `storage/db_pool.py:SQLitePool` | sí | `get_pool(db)` | — |
| db_connect_pooled | `:db_connect_pooled` | sí | `db_connect_pooled(db)` | — |
| _PooledConnection.__del__ gc_reclaim | `:_PooledConnection.__del__` | sí | test | — |
| pool_stats | `:pool_stats` | sí | `pool_stats()` | — |
| close_pool | `:close_pool` | sí | `close_pool(db)` | — |
| vacuum | `:vacuum` | sí | `vacuum(db)` | único sqlite3.connect legítimo |
| key_manager.KeyManager (AES-256-GCM) | `security/key_manager.py` | sí | `KeyManager(...).unlock(p)` | fallback XOR degradado si falta `cryptography` |
| encrypt_text_decrypt_text | `:encrypt_text` | sí | `km.encrypt_text(x)` | — |
| get_key_manager (singleton) | `:get_key_manager` | sí | `get_key_manager()` | clave se pierde al reiniciar (diseño) |
| secure_storage.SecureEpisodicMemory | `security/secure_storage.py` | sí | `/desbloquear <pass>` | opera en claro con warning si bloqueado |
| reencrypt_all (rotación) | `:reencrypt_all` | sí | `m.reencrypt_all(new)` | — |
| status (cobertura cifrado) | `:status` | sí | `/seguridad` | — |
| cli.seguridad_bloquear_desbloquear | `cli.py` → `cognia.py` | sí | `/desbloquear <p>` | — |
| migrate_db_encrypt | `scripts/migrate_db_encrypt.py` | **no** | `python scripts/migrate_db_encrypt.py` | no empaquetado |
| ollama_url.validate_ollama_url (anti-SSRF) | `security/ollama_url.py` | sí | `validate_ollama_url(u)` | — |
| code_executor.validate_python | `cognia_v3/interfaces/code_executor.py` | sí | `validate_python(c)` | — |
| validate_generated_module_imports (allowlist AST) | `:validate_generated_module_imports` | sí | idem | regla 9 CLAUDE.md |
| run_python (subprocess sandbox) | `:run_python` | sí | `run_python(c)` | timeout 15s |
| run_javascript | `:run_javascript` | sí | `run_javascript(c)` | requiere Node |
| validate_html_css | `:validate_html/css` | sí | `validate_html(x)` | — |
| CodeExecutor_class | `:CodeExecutor` | sí | `get_code_executor()` | — |
| sandbox_tester.SandboxTester | `cognia_v3/core/sandbox_tester.py` | sí | `SandboxTester().test_module_from_code(...)` | — |
| sandbox_runner.run_in_sandbox (doble capa) | `cognia/program_creator/sandbox_runner.py` | sí | `run_in_sandbox(c)` | — |

---

## Área 9 — web-server (90 features)

Tres servidores distintos. **app/ (v3, :8000) y coordinator/ = `packaged=sí`; cognia_desktop_api.py (:8765) y cognia_public_api/ = `packaged=no`** (viven en raíz/paquete excluido; solo corren desde el checkout, la app Electron los invoca como script).

### 9a. app/ FastAPI v3 (:8000) — packaged=sí

| feature | entry_point | model_dep | invocar | riesgo |
|---|---|---|---|---|
| app-fastapi-v3-api | `app/main.py:app` | no | `uvicorn app.main:app` | distinto/menor que desktop_api; verificar cuál usa producción |
| chat-post-api-chat | `app/routes/chat.py:chat` | sí | `POST /api/chat` | — |
| status-health-api-health | `status.py:health` | no | `GET /api/health` | — |
| status-api-status | `status.py:status` | no | `GET /api/status` | — |
| status-api-conceptos | `status.py:conceptos` | no | `GET /api/conceptos` | — |
| gdpr-export-user-data | `user_data.py:export` | no | `GET /api/user/data/export` | requiere X-Admin-Key |
| gdpr-delete-user-data | `user_data.py:delete` | no | `DELETE /api/user/data` | **irreversible, borra TODA la memoria sin scoping** |

### 9b. cognia_desktop_api.py (:8765) — packaged=NO

| feature | entry_point | model_dep | invocar | riesgo |
|---|---|---|---|---|
| desktop-api-infer (~15 subsistemas) | `:infer` | sí | `POST /infer` | **no empaquetado; solo repo/Electron** |
| desktop-api-route | `:route` | no | `GET /route` | no empaquetado |
| desktop-api-infer-stream-v2 | `:infer_stream_v2` | sí | `POST /infer-stream-v2` | no empaquetado |
| desktop-api-infer-stream | `:infer_stream` | sí | `GET /infer-stream` | no empaquetado |
| desktop-api-status | `:status` | no | `GET /status` | no empaquetado |
| desktop-api-ready | `:ready` | no | `GET /ready` | no empaquetado |
| desktop-api-health-performance | `:health_performance` | sí | `GET /health/performance` | no empaquetado |
| desktop-api-chat-history | `:get/save/delete_chat_history` | no | `GET /chat/history` | no empaquetado |
| desktop-api-session-summaries | `:get_session_summaries` | no | `GET /sessions/{id}/summaries` | no empaquetado |
| desktop-api-agent | `:run_agent` | sí | `POST /agent` | no empaquetado |
| desktop-api-skills | `:list_skills/get_skill` | no | `GET /skills` | no empaquetado |
| desktop-api-network-status | `:network_status` | no | `GET /network/status` | no empaquetado |
| desktop-api-cache-stats | `:cache_stats` | no | `GET /api/cache/stats` | no empaquetado |
| desktop-api-health | `:health` | no | `GET /health` | no empaquetado |
| desktop-api-mode-settings | `:get/set_mode/settings` | no | `POST /mode` | no empaquetado |
| desktop-api-persona | `:set/list/get_persona` | no | `GET /persona/list` | no empaquetado |
| desktop-api-goals | `:create/list_goals...` | no | `POST /goals` | no empaquetado |
| desktop-api-webhooks | `:webhooks_*` | no | `POST /webhooks` | no empaquetado |
| desktop-api-curiosity-gaps | `:curiosity_insights/gaps` | no | `GET /curiosity/insights` | no empaquetado |
| desktop-api-insights-contradictions | `:insights/contradictions` | no | `GET /insights` | no empaquetado |
| desktop-api-kg-multihop | `:kg_multihop_*` | no | `GET /kg/multihop/path` | no empaquetado |
| desktop-api-ollama-proxy | `:ollama_generate` | sí | `POST /api/generate` | no empaquetado |
| desktop-api-file-browser | `:list/read/write_file` | no | `GET /files/list` | **escritura sin auth en workspace; revisar LAN_MODE** |
| desktop-api-auth-keys | `:auth_*` | no | `POST /auth/keys` | no empaquetado |
| desktop-api-metrics-dashboard | `:get_metrics/dashboard` | no | `GET /dashboard` | no empaquetado |
| desktop-api-search | `:web_search` | no | `GET /search` | requiere red (DuckDuckGo) |
| desktop-api-export-history | `:export_history/stats` | no | `GET /export/history` | no empaquetado |
| desktop-api-tools-route | `:tools_route` | no | `POST /tools/route` | no empaquetado |
| desktop-api-report-progress | `:report_progress/stats` | no | `GET /report/progress` | no empaquetado |
| desktop-api-quality | `:quality_*` | no | `GET /quality/summary` | no empaquetado |
| desktop-api-notifications | `:notifications_*` | no | `GET /notifications/{u}` | no empaquetado |
| desktop-api-reminders | `:reminders_*` | no | `POST /reminders` | no empaquetado |
| desktop-api-templates | `:*_template*` | no | `GET /templates` | no empaquetado |
| desktop-api-debug-state | `:debug_state` | no | `GET /debug/state` | requiere X-Admin-Key |
| desktop-api-debug-health | `:debug_health` | no | `GET /debug/health` | no empaquetado |
| desktop-api-feedback | `:feedback_*` | no | `POST /feedback` | no empaquetado |
| desktop-api-proactive | `:proactive_*` | no | `GET /proactive/suggestions` | no empaquetado |
| desktop-api-notes | `:notes_*` | no | `POST /notes` | no empaquetado |
| desktop-api-spaced-repetition | `:sr_*` | no | `POST /learning/cards` | no empaquetado |
| desktop-api-quiz | `:quiz_*` | no | `GET /quiz/generate` | no empaquetado |
| desktop-api-achievements | `:achievements_*` | no | `GET /achievements` | no empaquetado |
| desktop-api-analytics | `:analytics_*` | no | `GET /analytics/stats` | no empaquetado |
| desktop-api-memory-search | `:memory_search` | no | `GET /memory/search` | no empaquetado |
| desktop-api-synthesis | `:synthesis_endpoint` | no | `GET /synthesis` | no empaquetado |
| desktop-api-cognitive-profile | `:cognitive_profile_*` | no | `GET /cognitive-profile` | no empaquetado |
| desktop-api-recommendations | `:recommendations_*` | no | `GET /recommendations` | no empaquetado |
| desktop-api-critique | `:critique_*` | no | `GET /critique/score` | no empaquetado |
| desktop-api-anchor-debug | `:anchor_debug` | no | `GET /anchor/{sid}` | no empaquetado |
| desktop-api-style-profile | `:style_profile` | no | `GET /style/profile` | no empaquetado |
| desktop-api-reports | `:reports_*` | no | `GET /reports/generate` | no empaquetado |
| desktop-api-feature-flags | `:features_*` | no | `GET /features` | PATCH requiere X-Admin-Key |
| desktop-api-knowledge-crystallization | `:knowledge_crystal*` | no | `POST /knowledge/crystallize` | no empaquetado |
| desktop-api-knowledge-conflicts | `:knowledge_conflicts_*` | no | `POST /knowledge/conflicts/check` | no empaquetado |
| desktop-api-learning-paths | `:learning_path_*` | no | `POST /learning/paths` | no empaquetado |
| desktop-api-user-facts | `:user_facts_*` | no | `POST /user/facts` | no empaquetado |
| desktop-api-context-prioritizer-stats | `:context_prioritizer_stats` | no | `GET /context/prioritizer-stats` | no empaquetado |
| desktop-api-digest | `:digest_get` | no | `GET /digest` | no empaquetado |
| desktop-api-format-detect | `:format_detect` | no | `GET /format/detect` | no empaquetado |
| desktop-api-memory-consolidation | `:memory_consolidate` | no | `POST /memory/consolidate` | no empaquetado |
| desktop-api-cors-lan-mode | `:_LAN_MODE` | no | `COGNIA_LAN_MODE=1` | **abre CORS ampliamente para móvil** |
| desktop-api-key-auth-middleware | `:_api_key_middleware` | no | `X-API-Key` | no empaquetado |

### 9c. cognia_public_api/ (Railway) — packaged=NO

| feature | entry_point | model_dep | invocar | riesgo |
|---|---|---|---|---|
| public-api-health | `cognia_public_api/app.py:health` | no | `GET /health` | **paquete excluido; solo deploy directo** |
| public-api-status | `:status` | no | `GET /v1/status` | no empaquetado |
| public-api-create-key | `:create_key` | no | `POST /v1/keys/create` | rate-limit 5/h |
| public-api-generate | `:generate` | sí | `POST /v1/generate` | requiere Bearer |
| public-api-shard-autodownload | `:lifespan/_try_download_shard` | no | `HF_TOKEN=...` | descarga HF |

### 9d. coordinator/ (swarm, Railway) — packaged=sí (online, apagar por default)

| feature | entry_point | model_dep | invocar | riesgo |
|---|---|---|---|---|
| coordinator-node-register | `coordinator/app.py:register_node` | no | `POST /api/node/register` | online |
| coordinator-node-heartbeat | `:node_heartbeat` | no | `POST /api/node/heartbeat` | online |
| coordinator-node-unregister | `:unregister_node/node_leave` | no | `POST /api/node/leave` | online |
| coordinator-swarm-status | `:swarm_status` | no | `GET /api/swarm/status` | online |
| coordinator-swarm-replication | `:swarm_replication` | no | `GET /api/swarm/replication` | online |
| coordinator-swarm-route | `:get_route` | no | `GET /api/swarm/route` | online |
| coordinator-models-config | `:model_config/list_models` | no | `GET /api/models` | online |
| coordinator-session-infer-http | `:create_session/session_infer` | sí | `POST /api/session/create` | requiere nodos → 503/504 |
| coordinator-shattering-route | `:shattering_route` | no | `GET /api/shattering/route` | online |
| coordinator-shattering-status | `:shattering_status` | no | `GET /api/shattering/status` | online |
| coordinator-shattering-infer | `:shattering_infer` | sí | `POST /api/shattering/infer` | requiere nodos → 503 |
| coordinator-tiers-contribution | `:list_tiers/get_contribution` | no | `GET /api/tiers` | online |
| coordinator-federated-learning | `:federated_*` | no | `POST /api/federated/contribute` | solo adapters LoRA; DP en cliente |
| coordinator-event-bus-ws | `:events_ws/history` | no | `WS /ws/events` | online |
| coordinator-relay-ws | `:websocket_relay/pending_sessions` | no | `WS /ws/relay/{sid}/{n}` | online |
| coordinator-health-ready-root | `:ready/health/root` | no | `GET /ready` | online |
| coordinator-entrypoint-cli | `coordinator/run.py:main` | no | `cognia-coordinator` | online |

---

## Área 10 — packaging-install (16 features)

`packaged=sí`: lo que viaja en el wheel/es referenciado por él. `packaged=no`: instaladores/scripts/artefactos que solo existen en el repo o son canales de distribución separados. Todas cero-LLM.

| feature | entry_point | packaged | invocar | riesgo |
|---|---|---|---|---|
| pyproject_metadata_scripts (cognia-ai v3.7.1) | `pyproject.toml:[project.scripts]` | sí | `pip install -e .` | — |
| pyproject_optional_extras | `[optional-dependencies]` | sí | `pip install cognia-ai[semantic]` | — |
| pyproject_packages_find_scope | `[packages.find]` | sí | inspección wheel | **excluye a propósito cognia_x/desktop/game/mobile/public_api** |
| pyproject_package_data | `[package-data]` | sí | inspección wheel | — |
| manifest_in_sdist | `MANIFEST.in` | sí | `tar tzf ...` | — |
| install_ps1_windows_bootstrap | `install.ps1` | **no** | `irm URL \| iex` | usa requirements.txt COMPLETO (arrastra torch) |
| install_sh_unix_bootstrap | `install.sh` | **no** | `curl \| bash` | idem torch |
| cognia_setup_py_engine | `scripts/cognia_setup.py` | **no** | `python scripts/cognia_setup.py` | escribe ~/.cognia/.env |
| cognia_first_run_wizard | `cognia/first_run.py:run_wizard` | sí | `cognia` (1ra vez) | escribe ~/.cognia/config.env (archivo DISTINTO del .env de setup) |
| cognia_cli_subcommands | `cognia/__main__.py:main` | sí | `cognia help` | — |
| inno_setup_windows_gui_installer | `installer/cognia_setup.iss` | **no** | `ISCC.exe ...` | **AppVersion 3.2.0 desincronizado vs 3.7.1** |
| inno_launcher_ps1 | `installer/cognia_launcher.ps1` | **no** | `powershell -File ...` | — |
| prebuilt_inno_exe | `installer/dist/cognia-setup.exe` | **no** | correr el .exe | artefacto en repo |
| prebuilt_pypi_dist | `dist/cognia_ai-3.7.1*` | sí | `pip install dist/...whl` | no subir a PyPI sin autorización |
| cognia_desktop_electron_installer | `cognia_desktop/electron-builder.config.js` | **no** | `npm run build:win` | **canal/versionado separado (Electron 1.1.0 vs pip 3.7.1); 2 configs no unificadas** |
| requirements_txt_drift | `requirements.txt` | **no** | usado por install.ps1/sh | **instala torch/sentence-transformers incondicionalmente; contradice "lean core"; prometheus no está en pyproject** |

---

# CONCLUSIONES

## (a) Conteo total

**568 features** verificadas contra el catálogo (suma exacta por área):

| # | Área | Features |
|---|---|---|
| 1 | cli-commands | 222 |
| 2 | agent-loop-tools | 54 |
| 3 | rsi-autoprompt | 18 |
| 4 | memory | 42 |
| 5 | image-lcd-beta | 33 |
| 6 | model-backend | 46 |
| 7 | online-swarm | 24 |
| 8 | storage-security | 23 |
| 9 | web-server | 90 |
| 10 | packaging-install | 16 |
| | **TOTAL** | **568** |

## (b) Features NO empaquetadas que el dueño querría en la versión comercial

Prioridad ordenada:

1. **CREADOR DE IMÁGENES/ESCENAS (área 5 completa, 33 features) — EL MÁS IMPORTANTE, HOY EXCLUIDO.** Todo `cognia_x/lcd/` es `packaged=no` porque `cognia_x` está en el `exclude` de `pyproject.toml`, y el import en `cli.py:7284` está en try/except best-effort → **en el wheel actual las 37 tools de escena NUNCA se registran; es código muerto para el usuario final de pip.** Incluye `escena_crear/editar/consultar`, `render_aprox`, las 8 herramientas de modelado tipo-Blender, `escena_animar_caida` (GIF), plantillas, export SVG/JSON, y el árbitro de atribución cero-LLM. **Fix:** (a) sacar `cognia_x` del exclude e incluir `cognia_x.lcd` en `packages.find` + agregar `Pillow` a dependencies, o (b) mover `lcd/` a `cognia/lcd` o `cognia_v3/lcd`. Sin esto, no hay creador de imágenes en la versión comercial.

2. **`llama_server_backend` + el binario `node/llama-server.exe`** (área 6): `packaged=no`. Es uno de los dos caminos de inferencia real (el otro es `llama-cpp-python`). Si se depende de `llama-server.exe` hay que resolver cómo distribuirlo (no cabe en el wheel PyPI; probablemente va por el canal Electron o descarga en setup). Verificar que `llama-cpp-python` cubra el caso pip puro.

3. **`generated_tools/` hot-load** (área 2): el directorio de tools sintetizadas por HERMES no está en `package-data`; en pip fresco arranca vacío (comportamiento correcto, pero no persiste el catálogo semilla entre instalaciones). Considerar empaquetar un set base.

4. **Extras de larga generación ya están empaquetados** (`generate_long/hierarchical/delegated`) — no hace falta acción, solo notar que son la palanca comercial de "salidas largas".

Notas menores (probablemente OK que sigan fuera del pip): `/update`, `/distill`, `scripts/cognia_setup.py`, `migrate_db_encrypt.py`, instaladores Inno/Electron, `cognia_desktop_api.py`, `cognia_public_api/`. Son scripts de dev, infra o canales de distribución alternativos — no features de producto.

## (c) Piezas de ORQUESTACIÓN ONLINE a desactivar por default

El swarm YA está apagado por default (no toca `node/`/`coordinator/` salvo subcomando explícito o env var), pero el interruptor es **implícito** (env var `COGNIA_COORDINATOR_URL`/`COORDINATOR_URL`), no un flag documentado. **Recomendación central: agregar un flag duro `COGNIA_DISABLE_SWARM=1` que fuerce off aunque la env var esté seteada por error.**

Piezas a asegurar apagadas por default en la versión comercial local-only:

- **`inference_pipeline_distributed` / `language_engine.py:_call_swarm`** — el punto REAL por el que el swarm puede colarse en la generación de texto del engine legacy si la env var está seteada. Máxima prioridad de guard.
- **`distributed_infer`** (orchestrator) y **`coordinator-session-infer-http` / `shattering-infer`** — inferencia distribuida.
- **`cognia_node_cmd` / `cognia_coordinator_cmd`** — subcomandos `cognia node` / `cognia coordinator` (no ejecutar; documentar como avanzado).
- **`mesh_node_p2p_knowledge`** — el singleton `CogniaMeshNode` se instancia SIEMPRE al iniciar Cognia (pasivo, no abre sockets hasta `start_mesh()`); verificar/garantizar que nunca abra puerto por default, y ocultar `/mesh_*` del REPL en modo sencillo.
- **`federated_learning_fedavg` / `coordinator-federated-learning`** — FedAvg de adapters LoRA; capa contributora, apagar.
- **`contributor_tiers_ledger`, `event_bus_websocket`, `relay_websocket_pipeline`, `sar_shard_availability_redundancy`** — toda la maquinaria del coordinador.
- **`cli_modo_compartido`** (`cognia modo compartido`) — dejar `cognia modo local` como default; el modo compartido no arranca nada solo pero es la puerta de entrada al swarm.
- **`shard_downloader` con `--coordinator`** — permitir solo `--standalone` (local) en el flujo comercial.
- **`web-server` coordinator/ endpoints (17 features, área 9d)** — no exponer.

Riesgos de seguridad a revisar si algún modo online se habilita: `desktop-api-file-browser` (escritura sin auth), `desktop-api-cors-lan-mode` (CORS abierto), `/api/session/infer` sin auth por default, DP federado no forzado server-side.

## (d) Model-dependent (serial, cuello del 3B) vs cero-LLM (paralelizable) — para planear la verificación E2E

**Cero-LLM (paralelizables; verificables sin arrancar el modelo, con el harness/función directa)** — la gran mayoría del inventario, ~**460 features**. Bloques enteros: casi toda `memory` (40/42), toda `storage-security` (23/23), casi todo `packaging-install`, casi toda `image-lcd-beta` (31/33 tools de escena son puramente determinísticas), el andamiaje cero-LLM del agente (parsers, sandbox, contadores, goal_contract, tier lifecycle, verify_tool), la mayoría de comandos REPL de gestión (metas/notas/KG/historial/config), y casi todos los endpoints de estado/CRUD del web-server. **Estos se pueden verificar en paralelo** (invocación directa por función o `run_tool`), sin llama-server, y son el 80% de la superficie — la verificación E2E de todo esto es barata y masivamente paralelizable.

**Model-dependent (serial, cuello del 3B; requieren llama.cpp/GGUF o Ollama vivo)** — ~**108 features**. Concentradas en:
- **cli-commands:** ~50 comandos REPL creativos/de razonamiento (`/hacer`, `/pensar`, `/deliberar`, `/flujo`, `/largo`, `/hipotesis`, `/explicar`, `/razonar`, `/crear`, `/quiz`, `/debate`, `/sintetizar`, chat libre, etc.).
- **agent-loop-tools:** el loop ReAct (`agent_loop_react`), BoN (`best_of_n_judge`, `tool_generar_codigo`), HERMES (`crear_herramienta`), `delegar_subtarea`, `dynamic_step_budget`, `generate_then_structure`, `tool_resumir`, `skill_auto_apply`.
- **rsi-autoprompt:** `evolve`, `score_scaffold`, `bootstrap_exemplars`, `crear_herramienta`, `handle_live_failure` (los 5 model-dep; el resto son cero-LLM).
- **model-backend:** todos los caminos de inferencia (`infer`, `astream*`, `_shard_infer`, `_ollama_infer`, `_distributed_infer`, `generate_long/hierarchical/delegated`, `try_load_llama`, `reload_llama`, `grammar_constrained`, `speculative_decoding`).
- **memory:** solo 2 (`curiosity_queue_processing`, `active_curiosity_engine_wiring`).
- **image-lcd-beta:** 1 tool (`escena_crear` fallback) + el harness `motor_interno` (eval_llm_planner/eval_selfplay).
- **web-server:** ~10 endpoints de inferencia (`/api/chat`, `/infer*`, `/agent`, `/api/generate`, `/v1/generate`, `shattering_infer`, etc.).
- **online-swarm:** los que ejecutan inferencia real sobre shards.

**Plan de verificación E2E sugerido:** (1) barrer TODAS las cero-LLM en paralelo con el venv312 (invocación directa/pytest dirigido, sin backend) — cubre ~80% y es rápido; (2) arrancar UN llama-server (3B GGUF Q4_K_M) y correr las model-dependent en serie contra ese único backend (comparten el cuello), priorizando el camino crítico `/hacer` → loop ReAct → BoN → goal_contract, `/pensar`/`/deliberar`, y `generate_long` (salidas largas comerciales); (3) los caminos swarm/distribuidos NO verificarlos en la versión comercial (quedan apagados por default). El árbitro cero-LLM del área 5 (`atribuir_fallo`, `e2e_agente_escena`) es la pieza clave a verificar en paralelo si se decide empaquetar el creador de imágenes.