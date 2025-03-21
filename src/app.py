"""
import necessary modules:
    json to parse responses from the llm
    streamlit for the app
    pandas to work with tables/excel files
    ollama for llm processing
"""

import json
import streamlit as st
import pandas as pd
import ollama  # For local LLM processing


def load_abbreviation_dict(file_path):
    """
    Reads abbreviation_dict.xlsx and creates a mapping of abbreviations to the
    full words

    Args:
        file_path (str): path to abbreviation_dict.xlsx

    Returns:
        abbreviation_map (dict): dictionary that maps the abbreviations to
        their full words.
    """
    df = pd.read_excel(file_path)
    abbreviation_map = {}
    for _, row in df.iterrows():
        full_word = row["Full_words"]
        abbreviations = row["Abbreviation"].split(", ")
        for abbr in abbreviations:
            if abbr in abbreviation_map:
                abbreviation_map[abbr].append(full_word)
            else:
                abbreviation_map[abbr] = [full_word]
    return abbreviation_map


def resolve_abbreviation_with_llm(abbreviation, context, possible_words):
    """
    Use LLM to infer the full form of an abbreviation given its context.

    Args:
        abbreviation (str): The abbreviation in the transaction.
        context (str): The full transaction text.
        possible_words (list of str): Suggested full words from the dictionary.

    Returns:
        str: The most likely full word for the abbreviation.
    """
    prompt = f"""
    Bạn là một AI có nhiệm vụ giải thích các từ viết tắt trong giao dịch tài 
    chính. Dưới đây là ngữ cảnh:
    
    Giao dịch: "{context}"
    
    Từ viết tắt "{abbreviation}" có thể mang nghĩa nào? Các từ sau có thể là 
    gợi ý từ từ điển: {', '.join(possible_words)}.
    
    Nếu có từ nào phù hợp hơn dựa trên ngữ cảnh, hãy sử dụng nó.
    
    Hãy trả lời chỉ bằng từ đúng nhất.
    """

    response = ollama.chat(
        model="mistral", messages=[{"role": "user", "content": prompt}]
    )

    full_word = response["message"]["content"].strip()

    # Fallback: If the LLM response isn't useful, pick the first suggested word
    if full_word not in possible_words:
        full_word = possible_words[0]

    return full_word


def expand_abbreviations(text, abbreviation_map):
    """
    Replaces the abbreviation with the full word.
    This function finds the abbreviations in a text (remark), then replaces it
    with the most appropriate full words.

    Args:
        text (str): remark
        abbreviation_map (dict): dictionary that defines what the abbreviations
        could stand for

    Returns:
        (str): the text that have had its abbreviations replaced by the full
        words
    """
    words = text.split()
    expanded_words = []
    for word in words:
        if word in abbreviation_map:
            possible_words = abbreviation_map[word]
            if len(possible_words) == 1:
                expanded_words.append(possible_words[0])
            else:
                expanded_words.append(
                    resolve_abbreviation_with_llm(word, text, possible_words)
                )
        else:
            expanded_words.append(word)
    return " ".join(expanded_words)


st.title("Transaction Categorizer with Local LLM")

# Upload files
categories_file = st.file_uploader(
    "Upload Categories File (Excel)", type=["xls", "xlsx"]
)
transactions_file = st.file_uploader(
    "Upload Transactions File (Excel)", type=["xls", "xlsx"]
)
# Define the abbreviation_dict path, adjust path if necessary
abbreviation_dict_path = "../data/abbreviation_dict.xlsx"

if categories_file and transactions_file:
    # Load data
    categories_df = pd.read_excel(categories_file)
    transactions_df = pd.read_excel(transactions_file)
    abbreviation_map = load_abbreviation_dict(abbreviation_dict_path)

    st.write("### Transaction Categories")
    st.dataframe(categories_df)

    st.write("### Transactions")
    st.dataframe(transactions_df.head())

    # Ensure category column exists
    category_list = categories_df.iloc[:, 0].tolist()  # First column as category names

    # Expand abbreviations in transactions
    transactions_df["REMARK"] = transactions_df["REMARK_CLEAN"].apply(
        lambda x: expand_abbreviations(str(x), abbreviation_map)
    )

    # Prepare prompt
    # transactions_text = "\n".join(transactions_df["REMARK"].astype(str).tolist())
    # prompt = f"""
    # You are an AI trained to classify financial transactions into categories.
    # The available categories are: {', '.join(category_list)}.
    #
    # Classify the following transactions into one of the categories:
    # {transactions_text}
    #
    # Return the response as a JSON list of dictionaries with 'transaction' and 'category'.
    # """

    # Prepare Vietnamese prompt
    transactions_text = "\n".join(transactions_df["REMARK_CLEAN"].astype(str).tolist())
    prompt = f"""
    Bạn là một AI có nhiệm vụ phân loại giao dịch tài chính vào các danh mục 
    phù hợp. Danh mục có sẵn là: {', '.join(category_list)}.
    
    Hãy phân loại các giao dịch sau vào một trong các danh mục trên:
    {transactions_text}
    
    Trả lời dưới dạng danh sách JSON gồm các từ điển chứa 'transaction' và 
    'category'.
    """

    # Run LLM classification
    response = ollama.chat(
        model="mistral", messages=[{"role": "user", "content": prompt}]
    )

    try:
        response_content = response["message"]["content"]
        categorized_transactions = json.loads(response_content)

        # Check for missing transactions
        missing_count = len(transactions_df) - len(categorized_transactions)

        if missing_count > 0:
            st.warning(
                f"⚠️ {missing_count} transactions were not categorized. Assigning 'Uncategorized'."
            )

            # Create a DataFrame for missing transactions
            uncategorized_rows = transactions_df.iloc[
                len(categorized_transactions) :
            ].copy()
            uncategorized_rows["category"] = "Khác"

            # Append missing transactions back
            categorized_df = pd.concat(
                [pd.DataFrame(categorized_transactions), uncategorized_rows],
                ignore_index=True,
            )
        else:
            categorized_df = pd.DataFrame(categorized_transactions)

        # Display the categorized transactions
        st.write("### Categorized Transactions")
        st.dataframe(categorized_df)

        # Download button
        output_file = "categorized_transactions.xlsx"
        categorized_df.to_excel(output_file, index=False)
        with open(output_file, "rb") as file:
            st.download_button(
                "Download Categorized Transactions",
                file,
                file_name=output_file,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except json.JSONDecodeError as e:
        st.error(f"LLM response could not be processed as JSON: {e}")
