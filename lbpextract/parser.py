"""Parser module to convert LBP pdfs into csv files.

Note:

    pypdf doesn't work well for LBP documents

Example:

    lbpextract *.pdf

"""

import argparse
import glob
import json
import logging
import os
import re
import shutil
from glob import glob
from typing import Any, Dict, Tuple
import fitz  # PyMuPDF
import pandas as pd
from systemtools.number import getAllNumbers, getFirstNumber
from systemtools.printer import b, bp
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
section_types = [
    "main",
    "connexion",
    "page",
    "decouvert",
    "vos_operations",
    "old_amount",
    "new_amount",
    "columns",
    "total",
    "situation",
    "bon_a_savoir",
    "epargne",
    "operation_suite",
    "operation",
    "account",
    "page_head",
    "operation_suite",
]
black_snippets = [
    "Banque Postale fait évoluer les conditions",
    "Désormais, nous vous informons que La Banque",
    "communiquera toute information utile relative",
    "Assureurs dans les traitements consécutifs au",
    "seront remises en bureau de poste sur simple",
    "contestation écrite dans un délai",
    "vous pouvez résilier les services concernés",
    "contrats.",
    "OPPOSITION EN CAS DE PERTE OU DE VOL",
    "Appelez immédiatement le",
    "3639 (2) 24h/24 et 7j/7 (3).",
    "défaut, pour vos cartes de paiement et de retrait",
    "opposition des cartes 7j/7 et 24h",
    "QUELLES GARANTIES POUR VOS DÉPÔTS",
    "euros par personne. Le plafond",
    "DANS LES 48 HEURES À VOTRE",
    "UN DIFFÉREND OU UNE DIFFICULTÉ",
    "numéro dédié à la bonne exécution",
    "plus tard sous 10 jours ouvrables",
    "n’avez pas eu de réponse",
    "Médiateur exerce sa fonction en",
    "européenne de Règlement en Ligne",
    "conformément à nos engagements de banque",
    "Fonds de Garanties des Dépôts et de Résolution",
    "dépôts effectués sur vos comptes",
    "Service Clients par courrier à l’adresse indiquée",
    "satisfait pas, vous pouvez saisir gratuitement",
    "du Service Clients de La Banque Postale",
    " pouvez également effectuer votre déclaration",
    "s’applique à chaque déposant en cas de compte",
    "rencontrez une difﬁculté dans l’exécution",
    "Postale s’engage à répondre dans",
    "désaccord avec la réponse apportée",
    "document a été imprimé sur du papier",
    "ligne d'un produit ou service",
    "est conseillé de conserver ce relevé",
    "Pour votre information",
    "souhaitez déposer une réclamation",
    "Service Relation Recours",
    "75275 PARIS CEDEX 06",
    "sur le site Internet :",
    "Médiateur de La Banque",
    "Case Postale G ",
    "EPARDEPOT - 20",
    "PARIS CEDEX ",
    "IMPORTANT : DANS TOUS LES CAS",
    "recherche d’une solution",
    "La Banque Postale",
    "11 rue ",
    "l'étranger sont dorénavant gratuits",
    "Compte Jeunes. Profitez",
    "maîtrise sur toute la ligne ",
    "accessible avec un abonnement ",
    "auprès de votre Conseiller",
    "Renseignez-vous depuis votre espace",
    "Planifiez vos dépenses et optez",
    "automatique les factures régulières",
    "vous évitent toute mauvaise surprise",
    "remettre votre chèque à l’encaissement",
    "compte au verso",
    "Livret.",
    "Vous disposez désormais d'un compte sans plafond",
    "épargne tout en la conservant totalement disponible",
    "Simplicité, temps gagné, sans vous déplacer",
    "Pour en savoir plus, rendez-vous sur",
    "coûts de communication et de connexion",
    "connaître les différents types d’alertes",
]


def parse_pdf(path):
    lines = []
    coordinates = []
    for page in fitz.open(path):
        page_data = json.loads(page.get_text("json"))
        for block in page_data["blocks"]:
            for line in block["lines"]:
                current_text = ""
                for span in line["spans"]:
                    current_text += span["text"]
                lines.append(current_text)
                coordinates.append(span["origin"])
    return lines, coordinates


def parse_lbp_pdf(path):
    original_lines, original_coordinates = parse_pdf(path)
    lines = []
    coordinates = []
    for text, origin in zip(original_lines, original_coordinates):
        text = text.strip()
        if text == "":
            continue
        text = re.sub(r"\s+", " ", text.strip())
        if re.match(r"^\d\d/\d\d 4[A-Z].*$", text):
            lines.append(text[:5])
            lines.append(text[7:])
            coordinates.append(origin)
            coordinates.append(origin)
        else:
            lines.append(text)
            coordinates.append(origin)
    assert len(lines) == len(coordinates)
    return lines, coordinates


def is_number(line, regex=r"^[0-9 ,]+$"):
    return re.match(regex, line) is not None


def extract_short_date(string):
    assert len(string) == 5
    date = string.split("/")
    day, month = int(date[0]), int(date[1])
    return day, month


def is_section(section, lines, coordinates, index):
    try:
        parse_section(section, lines, coordinates, index)
        return True
    except:
        return False


def remove_sign_and_currency(text):
    text = text.strip()
    if text[0] in {"-", "+"}:
        text = text[1:]
    if text[-1] in {"¤", "€"}:
        text = text[:-1]
    return text.strip()


def parse_section(
    section, lines, coordinates, index, has_francs=False
) -> Tuple[Dict[str, Any], int]:
    """Parse a section given lines and a start index.

    This function is very strict and will fail if the section does not look
    as expected.

    It return a dict representing the data found in it and the next index after
    the section.
    """
    if section == "total":
        assert lines[index] == "Total des opérations"
        index += 1
        data = {"debit_and_credit": [getFirstNumber(lines[index])]}
        index += 1
        try:
            assert is_number(lines[index])
            data["debit_and_credit"] += [getFirstNumber(lines[index])]
            index += 1
        except:
            pass
        return data, index
    elif section == "operation_suite":
        assert re.match(r"Vos opérations .* n°.* \(suite\)", lines[index])
        return None, index + 1
    elif section == "page":
        assert re.match(r"^Page \d+/\d+$", lines[index])
        return None, index + 1
    elif section == "epargne":
        assert lines[index] == "Comptes d'Épargne"
        return None, index + 1
    elif section == "situation":
        assert "Situation de vos comptes" in lines[index]
        for current_index in range(index + 1, len(lines)):
            if is_section("account", lines, coordinates, current_index):
                return None, current_index
        raise Exception(f"Did not find the end of {section}.")
    elif section == "connexion":
        assert "Coût de connexion" in lines[index]
        for current_index in range(index + 1, len(lines)):
            if "vous est cons" in lines[current_index]:
                return None, current_index + 1
        raise Exception(f"Did not find the end of {section}.")
    elif section == "decouvert":
        assert " Découvert autorisé " in lines[index]
        for current_index in range(index + 1, len(lines)):
            if is_section("vos_operations", lines, coordinates, current_index):
                assert current_index - index < 20
                return None, current_index
            if is_section("columns", lines, coordinates, current_index):
                assert current_index - index < 20
                return None, current_index
        raise Exception(f"Did not find the end of {section}.")
    elif section == "main":
        assert "Relevé de" in lines[index]
        rest = "\n".join(lines[index + 1 : index + 30])
        assert "Vos" in rest and "Périodicité" in rest, rest
        for index in range(index, len(lines)):
            releve_string = "Relevé édité le "
            if releve_string in lines[index]:
                printed = lines[index][len(releve_string) :].strip()
                year = int(printed.split(" ")[-1])
                data = {"printed": printed, "year": year}
            elif is_section("situation", lines, coordinates, index):
                return data, index
            elif is_section("account", lines, coordinates, index):
                return data, index
        raise Exception(f"Did not find the end of {section}.")
    elif section == "account":
        number = lines[index].split("n°")[-1].replace(" ", "")
        index += 1
        assert "IBAN" in lines[index] and " | BIC" in lines[index], lines[
            index : index + 4
        ]
        return {"number": number}, index + 1
    elif section == "page_head":
        assert (
            lines[index].startswith("Relevé n")
            and " | " in lines[index]
            and "/" in lines[index]
        )
        index += 1
        assert "MR" in lines[index] or "MME" in lines[index]
        return None, index + 1
    elif section == "columns":
        assert lines[index] == "Date"
        index += 1
        assert lines[index].startswith("Opération")
        index += 1
        assert "Débit (" in lines[index]
        index += 1
        assert "Crédit (" in lines[index]
        index += 1
        if has_francs:
            assert "Soit en francs" in lines[index]
            index += 1
        return None, index
    elif section == "old_amount":
        assert "Ancien solde" in lines[index]
        date = lines[index].split(" au ")[-1]
        index += 1
        number_text = remove_sign_and_currency(lines[index])
        assert is_number(number_text)
        index += 1
        return {"date": date, "amount": getFirstNumber(number_text)}, index
    elif section == "new_amount":
        assert "ouveau solde au" in lines[index]
        date = lines[index].split(" au ")[-1]
        index += 1
        number_text = remove_sign_and_currency(lines[index])
        assert is_number(number_text)
        index += 1
        if has_francs:
            assert is_number(remove_sign_and_currency(lines[index]))
            index += 1
        return {"date": date, "amount": getFirstNumber(number_text)}, index
    elif section == "vos_operations":
        assert lines[index] == "Vos opérations"
        return None, index + 1
    elif section == "bon_a_savoir":
        assert lines[index].startswith("BON À SAVOIR")
        return None, len(lines)
    elif section == "operation":
        description = None
        if len(lines[index]) == 5:
            day, month = extract_short_date(lines[index])
        else:
            day, month = extract_short_date(lines[index][:5])
            description = lines[index][5:].strip()
        index += 1
        amount = None
        for current_index in range(index, len(lines)):
            if is_number(lines[current_index]):
                amount = getFirstNumber(lines[current_index])
                coordinate = coordinates[current_index][0]
                if has_francs:
                    if coordinate < 400:
                        sign = -1
                    else:
                        sign = 1
                else:
                    if coordinate < 490:
                        sign = -1
                    else:
                        sign = 1
                amount *= sign
                break
            else:
                if description is None:
                    description = lines[current_index]
                else:
                    description = f"{description} | {lines[current_index]}"
        if current_index - index >= 12:
            message = "\n".join(lines[index : index + 10])
            raise Exception(f"Too big operation:\n{message}")
        index = current_index + 1
        if has_francs:
            assert is_number(remove_sign_and_currency(lines[index]))
            index += 1
        assert amount is not None
        return {
            "day": day,
            "month": month,
            "amount": amount,
            "description": description,
        }, index


def parse_sections(lines, coordinates, has_francs=False):
    current_section = None
    end = None
    sections = []
    unrecognized_lines = []
    for start, line in enumerate(lines):
        if end is not None and start < end:
            continue
        found_a_section = False
        for section_type in section_types:
            if is_section(section_type, lines, coordinates, start):
                data, end = parse_section(
                    section_type,
                    lines,
                    coordinates,
                    start,
                    has_francs=has_francs,
                )
                sections.append((section_type, data))
                found_a_section = True
                break
        if not found_a_section:
            found_black = False
            for black_snippet in black_snippets:
                if black_snippet in line:
                    found_black = True
            if not found_black:
                logging.debug(f"Unrecognized line {start}:\n{line}")
                unrecognized_lines.append(line)
    unrecognized_lines = "\n".join(unrecognized_lines).strip()
    if unrecognized_lines:
        logging.warning(
            f"Unrecognized lines (please check if we missed important data):\n{unrecognized_lines}\n"
        )
    else:
        logging.info("No unrecognized line.")
    return sections


def process_table(sections):
    # Process dates:
    year = None
    months = set()
    for section_type, data in sections:
        if section_type == "main":
            year = data["year"]
        elif section_type == "operation":
            months.add(data["month"])
    assert year is not None, "Did not find the year of the document."
    assert len(months) is not None, "Too much months found in the document."
    # Add year in all operation:
    for section_type, data in sections:
        if section_type == "operation":
            if 1 in months and data["month"] == 12:
                data["year"] = year - 1
            else:
                data["year"] = year
    # Extract all data:
    current_account = None
    table = {}
    for section_type, data in sections:
        if section_type == "account":
            current_account = data["number"]
            table[current_account] = []
        elif section_type == "operation":
            assert (
                current_account is not None
            ), f"No account above this operation: {data}"
            table[current_account].append(
                {
                    "description": data["description"],
                    "date": f"{data['year']:04d}-{data['month']:02d}-{data['day']:02d}",
                    "amount": float(data["amount"]),
                }
            )
    return table


def main():
    parser = argparse.ArgumentParser(
        description="Convert La Banque Postale PDF files into CSV files"
    )

    parser.add_argument(
        "pdf_files",
        nargs="+",
        help="List of PDF files or a wildcard pattern (e.g., *.pdf)",
    )

    parser.add_argument(
        "--output-dir",
        help=(
            "Output directory for PDF files (default is the "
            "directory of the input files)"
        ),
    )

    args = parser.parse_args()
    pdf_files = []
    for pattern in args.pdf_files:
        pdf_files.extend(os.path.abspath(file) for file in glob(pattern))

    if not pdf_files:
        raise Exception("No PDF files found.")

    output_dir = args.output_dir
    if output_dir is None:
        first_file_dir = os.path.dirname(pdf_files[0])
        if all(os.path.dirname(file) == first_file_dir for file in pdf_files):
            output_dir = first_file_dir
        else:
            raise Exception(
                "Input files are in multiple directories."
                " Specify an output directory."
            )

    os.makedirs(output_dir, exist_ok=True)

    all_tables = []
    lines_set = set()
    duplicates = set()
    for file in tqdm(pdf_files):
        logging.info("Processing %s...", file)
        lines, coordinates = parse_lbp_pdf(file)
        current_hash = "\n".join(lines)
        if current_hash in lines_set:
            logging.error("File %s is a duplicate.", file)
            duplicates.add(file)
        else:
            lines_set.add(current_hash)
            logging.debug(b(list(zip(lines, coordinates)), 5))
            sections = parse_sections(
                lines,
                coordinates,
                has_francs="Soit en francs" in " ".join(lines),
            )
            table = process_table(sections)
            all_tables.append(table)
    if duplicates:
        logging.error("Duplicated files:\n" + "\n".join(list(duplicates)))
    table = {}
    for dictionary in all_tables:
        for key, value in dictionary.items():
            if key in table:
                table[key].extend(value)
            else:
                table[key] = value

    for key in table:
        output_path = f"{output_dir}/{key}.csv"
        if os.path.exists(output_path):
            raise FileExistsError(
                f"The file {output_path} already exists."
                " Please move or remove it before executing..."
            )
        df = pd.DataFrame(table[key])
        df = df[["date", "amount", "description"]]
        df = df.sort_values(by="date", ascending=False)
        df.to_csv(output_path, index=True, header=True)
        logging.info("%s created.", output_path)

    logging.info("Done.")


if __name__ == "__main__":
    main()
