from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.methodology import PerfilMetodologia
from core.loader import cargar_perfil

PERFILES_DIR = Path(__file__).parents[2] / "methodology" / "profiles"

PERFIL_MINIMO = """
autor: "TEST"
fuente: "tests"
version: "0.1.0"
deportes_soportados: ["running"]
reglas:
  - id: "TEST-CARGA-001"
    categoria: "Carga"
    descripcion: "Regla de prueba."
"""


def _escribir(tmp_path: Path, contenido: str) -> Path:
    ruta = tmp_path / "perfil.yaml"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


@pytest.mark.parametrize(
    "ruta", sorted(PERFILES_DIR.glob("*.yaml")), ids=lambda p: p.name
)
def test_todos_los_perfiles_del_repo_cargan(ruta):
    assert isinstance(cargar_perfil(ruta), PerfilMetodologia)


def test_carga_ejemplo_didactico():
    perfil = cargar_perfil(PERFILES_DIR / "ejemplo_didactico.yaml")
    assert perfil.autor == "EJEMPLO_DIDACTICO"
    assert len(perfil.reglas) == 4
    assert len(perfil.restricciones_globales) == 2
    assert len(perfil.reglas_secuenciales) == 2
    assert len(perfil.reglas_conteo_microciclo) == 2
    assert len(perfil.reglas_ajuste) == 2
    assert len(perfil.secuencias_bloques) == 2


def test_acepta_ruta_como_str(tmp_path):
    perfil = cargar_perfil(str(_escribir(tmp_path, PERFIL_MINIMO)))
    assert perfil.reglas[0].id == "TEST-CARGA-001"


def test_conserva_acentos_y_enie(tmp_path):
    perfil = cargar_perfil(_escribir(tmp_path, PERFIL_MINIMO.replace("Regla de prueba.", "Señal de progresión.")))
    assert perfil.reglas[0].descripcion == "Señal de progresión."


def test_ruta_inexistente_lanza_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        cargar_perfil(tmp_path / "no_existe.yaml")


def test_campo_obligatorio_ausente_lanza_validation_error(tmp_path):
    ruta = _escribir(tmp_path, PERFIL_MINIMO.replace('autor: "TEST"\n', ""))
    with pytest.raises(ValidationError, match="autor"):
        cargar_perfil(ruta)


def test_valor_de_enum_invalido_lanza_validation_error(tmp_path):
    ruta = _escribir(tmp_path, PERFIL_MINIMO.replace('"Carga"', '"Inventada"'))
    with pytest.raises(ValidationError, match="categoria"):
        cargar_perfil(ruta)


def test_ids_duplicados_lanza_validation_error(tmp_path):
    duplicado = PERFIL_MINIMO + """
reglas_conteo_microciclo:
  - id: "TEST-CARGA-001"
    descripcion: "Mismo id que la regla anterior."
    clase_sesion: "Descanso"
    minimo: 1
"""
    with pytest.raises(ValidationError, match="duplicados"):
        cargar_perfil(_escribir(tmp_path, duplicado))


def test_archivo_vacio_lanza_validation_error(tmp_path):
    with pytest.raises(ValidationError):
        cargar_perfil(_escribir(tmp_path, ""))


def test_yaml_mal_formado_lanza_yaml_error(tmp_path):
    with pytest.raises(yaml.YAMLError):
        cargar_perfil(_escribir(tmp_path, "autor: [sin cerrar\n"))


BORRADORES_DIR = PERFILES_DIR.parent / "borradores"


@pytest.mark.parametrize("ruta", sorted(BORRADORES_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_los_borradores_son_yaml_valido(ruta):
    # Un borrador no tiene que ser un perfil completo (no se carga para
    # planificar), pero sí YAML que se pueda leer al pasarlo a profiles/.
    assert isinstance(yaml.safe_load(ruta.read_text(encoding="utf-8")), dict)
