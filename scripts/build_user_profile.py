"""
scripts/build_user_profile.py
==============================
Script standalone para construir y mostrar el perfil de usuario a partir
del historial de chat.

USO:
    python scripts/build_user_profile.py [--session <id>] [--user <user_id>] [--limit 200]

Ejemplos:
    python scripts/build_user_profile.py
    python scripts/build_user_profile.py --session abc123
    python scripts/build_user_profile.py --user my_user --limit 500
"""

import argparse
import json
import sys
import os

# Asegurar que el directorio raiz del proyecto esta en el path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main():
    parser = argparse.ArgumentParser(
        description="Construye el perfil del usuario desde el historial de chat de Cognia."
    )
    parser.add_argument(
        "--session", default=None,
        help="Filtrar por session_id especifico (opcional)"
    )
    parser.add_argument(
        "--user", default="default",
        help="user_id para guardar/mostrar el perfil (default: 'default')"
    )
    parser.add_argument(
        "--limit", type=int, default=200,
        help="Numero maximo de mensajes a analizar (default: 200)"
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Guardar el perfil en la base de datos"
    )
    args = parser.parse_args()

    try:
        from cognia.profile.user_profile_builder import UserProfileBuilder
    except ImportError as e:
        print(f"ERROR: No se pudo importar UserProfileBuilder: {e}")
        sys.exit(1)

    builder = UserProfileBuilder()

    print(f"Analizando historial (session={args.session or 'todas'}, limit={args.limit})...")
    profile = builder.build_profile(session_id=args.session, limit=args.limit)

    print("\n--- PERFIL DEL USUARIO ---")
    print(f"Mensajes analizados : {profile['message_count']}")
    print(f"Longitud promedio   : {profile['avg_message_len']:.1f} chars")
    print(f"Idioma dominante    : {profile['dominant_language']}")

    print("\nTop temas:")
    if profile["top_topics"]:
        for i, t in enumerate(profile["top_topics"], 1):
            print(f"  {i:2d}. {t['term']:<20} ({t['count']} veces)")
    else:
        print("  (sin terminos detectados)")

    print("\nPatrones de consulta:")
    if profile["query_patterns"]:
        for p in profile["query_patterns"]:
            print(f"  - {p}")
    else:
        print("  (sin patrones detectados)")

    if args.save:
        builder.save_profile(args.user, profile)
        print(f"\nPerfil guardado para user_id='{args.user}'")
        ctx = builder.get_profile_context(args.user)
        print(f"Contexto inyectable: {ctx}")
    else:
        print("\n(Usa --save para persistir el perfil en la BD)")


if __name__ == "__main__":
    main()
