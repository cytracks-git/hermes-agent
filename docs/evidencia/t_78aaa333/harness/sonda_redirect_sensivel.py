"""Por que ``test_redirect_to_sensitive_target`` reprova nesta imagem.

Achado colateral do card t_78aaa333: este teste JA reprovava no HEAD sem o
patch (medido: mesma falha em ``90a45ec``), entao nao e regressao do conserto
do diagnostico. Mas "nao e meu" nao e "esta bom" -- esta sonda mede QUAL das
quatro formas do teste nao e reconhecida, para o achado ir ao card com causa
em vez de adjetivo.

Uso: python3 sonda_redirect_sensivel.py
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.approval import detect_dangerous_command


def main() -> int:
    print(f"REDIRECT HOME={os.environ.get('HOME')!r} path_home={str(Path.home())!r}")
    print(f"REDIRECT HERMES_HOME={os.environ.get('HERMES_HOME')!r}")
    alvo = Path.home() / ".ssh" / "authorized_keys"
    for comando in (
        "echo x > $HERMES_HOME/.env",
        "cat key >> $HOME/.ssh/authorized_keys",
        "cat key >> ~/.ssh/authorized_keys",
        f"cat key >> {alvo}",
    ):
        perigoso, chave, _ = detect_dangerous_command(comando)
        marca = "OK" if perigoso else "NAO_PEGOU"
        print(f"REDIRECT {marca} chave={chave!r} cmd={comando!r}")

    # A pergunta que decide se isto e artefato do laboratorio ou buraco real:
    # o caminho ABSOLUTO de um home de verdade e reconhecido? Se nao for, a
    # deteccao so enxerga ``~`` e ``$HOME`` literais -- e quem escrever o
    # caminho expandido passa direto. Nao da para responder isso por leitura.
    print("REDIRECT --- caminho absoluto de homes plausiveis ---")
    for home in ("/Users/alguem", "/home/alguem", "/root", "/tmp"):  # no-tmp: ok — denylist: detecta /tmp como home insegura
        cmd = f"cat key >> {home}/.ssh/authorized_keys"
        perigoso, chave, _ = detect_dangerous_command(cmd)
        print(f"REDIRECT {'OK' if perigoso else 'NAO_PEGOU'} chave={chave!r} cmd={cmd!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
