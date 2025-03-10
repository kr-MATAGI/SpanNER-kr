import random
import time
import copy

import numpy as np
import pickle

from eunjeon import Mecab
# from konlpy.tag import Mecab

from tag_def import ETRI_TAG, NIKL_POS_TAG, MECAB_POS_TAG
from data_def import Sentence, NE, Morp, Word

from gold_corpus_npy_maker import (
    conv_TTA_ne_category
)

from typing import List, Dict, Tuple
from transformers import ElectraTokenizer
from tokenization_kocharelectra import KoCharElectraTokenizer

# SPAN NER Package
from allennlp.data.dataset_readers.dataset_utils import enumerate_spans
from torch.utils.data import Dataset

# Global
test_str_list = [
    "문건 유출에 관여한 것으로 보이는 서울경찰청 정보1분실 직원 한모"
    "29·미국·사진", "전창수(42) 두산타워 마케팅팀 차장", "샌드위치→역(逆)샌드위치→신(新)샌드위치….",
    "홍준표·원희룡·나경원 후보가 '3강'을 형성하며 엎치락뒤치락해 왔다.", "P 불투르(Vulture) 인사위원회 위원장은",
    "넙치·굴비·홍어·톳·꼬시래기·굴·홍합", "연준 의장이", "황병서 북한군 총정치국장이 올해 10월 4일",
    "영업익 4482억 ‘깜짝’… LG전자 ‘부활의 노래’", "LG 우규민-삼성 웹스터(대구)",
    "‘김종영 그 절대를 향한’ 전시회", "재산증가액이 3억5000만원이다.", "‘진실·화해를 위한 과거사 정리위원회’",
    "용의자들은 25일 아침 9시께", "해외50여 개국에서 5500회 이상 공연하며 사물놀이",
    "REDD는 열대우림 등 산림자원을 보호하는 개도국이나",
    "2010년 12월부터 이미 가중 처벌을 시행하는 어린이 보호구역의 교통사고 발생 건수는",
    "금리설계형의 경우 변동금리(6개월 변동 코픽스 연동형)는", "현재 중국의 공항은 400여 개다.",
    "'중국 편'이라고 믿었던 박 대통령에게", "2001년 한·미 주둔군지위협정(소파·SOFA)"
]

g_SYMBOL_TAGS = [
    "SF", "SE", # (마침표, 물음표, 느낌표), 줄임표
    "SSO", "SSC", # 여는 괄호, 닫는 괄호
    "SC", "SY", # 구분자, (붙임표, 기타 기호)
]

#==========================================================================================
def load_ne_entity_list(src_path: str = ""):
#==========================================================================================
    all_sent_list = []

    with open(src_path, mode="rb") as pkl_file:
        all_sent_list = pickle.load(pkl_file)
        print(f"[mecab_npy_maker][load_ne_entity_list] all_sent_list size: {len(all_sent_list)}")
    all_sent_list = conv_TTA_ne_category(all_sent_list)

    return all_sent_list

#=======================================================================================
def convert2tokenIdx(all_span_idxs, span_idxLab):
#=======================================================================================
    # convert the all the span_idxs from word-level to token-level
    sidxs = [x1 for (x1, x2) in all_span_idxs]
    eidxs = [x2 for (x1, x2) in all_span_idxs]

    span_idxs_new_label = {}
    for ns, ne, ose in zip(sidxs, eidxs, all_span_idxs):
        os, oe = ose
        oes_str = "{};{}".format(os, oe)
        nes_str = "{};{}".format(ns, ne)
        if oes_str in span_idxLab:
            label = span_idxLab[oes_str]
            span_idxs_new_label[nes_str] = label
        else:
            span_idxs_new_label[nes_str] = 'O'

    return span_idxs_new_label


#=======================================================================================
def make_span_idx_label_pair(ne_list, text_tokens):
#=======================================================================================
    ret_dict = {}

    # print(text_tokens)
    b_check_use = [False for _ in range(len(text_tokens))]
    for ne_idx, ne_item in enumerate(ne_list):
        ne_char_list = list(ne_item.text.replace(" ", ""))

        concat_item_list = []
        for tok_idx in range(len(text_tokens)):
            if b_check_use[tok_idx]:
                continue
            for sub_idx in range(tok_idx + 1, len(text_tokens)):
                concat_word = ["".join(x).replace("##", "") for x in text_tokens[tok_idx:sub_idx]]
                concat_item_list.append(("".join(concat_word), (tok_idx, sub_idx - 1))) # Modify -1
        concat_item_list = [x for x in concat_item_list if "".join(ne_char_list) in x[0]]
        concat_item_list.sort(key=lambda x: len(x[0]))
        # print(ne_item.text, ne_item.type, concat_item_list)
        if 0 >= len(concat_item_list):
            continue
        target_idx_pair = concat_item_list[0][1]
        for bio_idx in range(target_idx_pair[0], target_idx_pair[1] + 1):
            b_check_use[bio_idx] = True
        key = str(target_idx_pair[0]) + ";" + str(target_idx_pair[1])
        ret_dict[key] = ne_item.type

    # print(ret_dict)
    return ret_dict

#=======================================================================================
def make_span_nn_josa_onehot(all_span_idx_list, nn_onehot, josa_onehot):
#=======================================================================================
    ret_nn_onehot_list = []
    ret_josa_onehot_list = []

    sidxs = [x1 for (x1, x2) in all_span_idx_list]
    eidxs = [x2 for (x1, x2) in all_span_idx_list]
    for s_i, e_i in zip(sidxs, eidxs):
        merge_nn_onehot = [0 for _ in range(5)] # nn[5]
        merge_josa_onehot = [0 for _ in range(9)] # josa[9] 개수
        for curr_idx in range(s_i, e_i+1):
            filter_nn_onehot = np.where(1 == np.array(nn_onehot[curr_idx]))[0]
            filter_josa_onehot = np.where(1 == np.array(josa_onehot[curr_idx]))[0]

            for nn_idx in filter_nn_onehot:
                merge_nn_onehot[nn_idx] = 1
            for josa_idx in filter_josa_onehot:
                merge_josa_onehot[josa_idx] = 1
        ret_nn_onehot_list.append(merge_nn_onehot)
        ret_josa_onehot_list.append(merge_josa_onehot)
    return ret_nn_onehot_list, ret_josa_onehot_list


#=======================================================================================
def convert_character_pos_tokens(sent_lvl_pos: Tuple[str, str], src_text: str):
#=======================================================================================
    # 어절별 글자 수 체크해서 띄워쓰기 적기
    split_text = src_text.split(" ")
    char_cnt_list = [len(st) for st in split_text]

    total_eojeol_morp = []
    use_check = [False for _ in range(len(sent_lvl_pos))]
    for char_cnt in char_cnt_list:
        curr_char_cnt = 0
        for ej_idx, eojeol in enumerate(sent_lvl_pos):
            if char_cnt == curr_char_cnt:
                total_eojeol_morp.append([" ", "O"])
                break
            if use_check[ej_idx]:
                continue
            total_eojeol_morp.append([eojeol[0], eojeol[1].split("+")])
            curr_char_cnt += len(eojeol[0])
            use_check[ej_idx] = True

    return total_eojeol_morp

#=======================================================================================
def convert_wordpiece_pos_tokens(sent_lvl_pos: Tuple[str, str], src_text: str):
#=======================================================================================
    # 어절별 글자 수 체크해서 띄워쓰기 적기
    split_text = src_text.split(" ")
    char_cnt_list = [len(st) for st in split_text]

    total_eojeol_morp = []
    use_check = [False for _ in range(len(sent_lvl_pos))]
    for char_cnt in char_cnt_list:
        curr_char_cnt = 0
        for ej_idx, eojeol in enumerate(sent_lvl_pos):
            if char_cnt == curr_char_cnt:
                break
            if use_check[ej_idx]:
                continue
            total_eojeol_morp.append([eojeol[0], eojeol[1].split("+")])
            curr_char_cnt += len(eojeol[0])
            use_check[ej_idx] = True

    return total_eojeol_morp

#=======================================================================================
def convert_morp_connected_tokens(sent_lvl_pos: Tuple[str, str], src_text: str):
#=======================================================================================
    ret_conv_morp_tokens = []

    # 어절별 글자 수 체크해서 띄워쓰기 적기
    split_text = src_text.split(" ")
    char_cnt_list = [len(st) for st in split_text]

    total_eojeol_morp = []
    use_check = [False for _ in range(len(sent_lvl_pos))]
    for char_cnt in char_cnt_list:
        eojeol_morp = []
        curr_char_cnt = 0
        for ej_idx, eojeol in enumerate(sent_lvl_pos):
            if char_cnt == curr_char_cnt:
                total_eojeol_morp.append(copy.deepcopy(eojeol_morp))
                eojeol_morp.clear()
                break
            if use_check[ej_idx]:
                continue
            eojeol_morp.append(eojeol)
            curr_char_cnt += len(eojeol[0])
            use_check[ej_idx] = True
        if 0 < len(eojeol_morp):
            total_eojeol_morp.append(eojeol_morp)

    for eojeol in total_eojeol_morp:
        for mp_idx, morp in enumerate(eojeol): # morp (마케팅, NNG)
            if 0 == mp_idx or morp[1] in g_SYMBOL_TAGS:
                ret_conv_morp_tokens.append((morp[0], morp[1], False))
            else:
                if eojeol[mp_idx-1][1] not in g_SYMBOL_TAGS:
                    conv_morp = (morp[0], morp[1], True)
                    ret_conv_morp_tokens.append(conv_morp)
                else:
                    ret_conv_morp_tokens.append((morp[0], morp[1], False))

    return ret_conv_morp_tokens

#=======================================================================================
def make_adapter_input(src_list: List[Sentence], tokenizer, max_length: int = 128):
#=======================================================================================
    input_ids_list: List = []
    attention_mask_list: List = []
    token_type_ids_list: List = []
    for src_idx, src_item in enumerate(src_list):
        if 0 == (src_idx % 10000):
            print(f"[make_adapter_input] {src_idx} - {src_item.text}")
        encoded = tokenizer.encode_plus(
            src_item.text,
            None,
            add_special_tokens=True,
            max_length=max_length,
            truncation=True,
            padding="max_length"
        )

        input_ids = encoded["input_ids"]
        attention_mask = encoded["attention_mask"]
        token_type_ids = encoded["token_type_ids"]

        assert max_length == len(input_ids), f"input_ids.len: {len(input_ids)}"
        assert max_length == len(attention_mask), f"attention_mask: {len(attention_mask)}"
        assert max_length == len(token_type_ids), f"token_type_ids: {len(token_type_ids)}"

        input_ids_list.append(input_ids)
        attention_mask_list.append(attention_mask)
        token_type_ids_list.append(token_type_ids)

    print("[make_adapter_input] Total Data:")
    print(f"input_ids.size: {len(input_ids_list)}")
    print(f"attention_mask.size: {len(attention_mask_list)}")
    print(f"token_type_ids.size: {len(token_type_ids_list)}")

    # Split Train/Dev/Test
    split_size = int(len(src_list) * 0.1)
    train_size = split_size * 7
    dev_size = train_size + split_size

    train_input_ids = np.array(input_ids_list[:train_size])
    train_attention_mask = np.array(attention_mask_list[:train_size])
    train_token_type_ids = np.array(token_type_ids_list[:train_size])
    print("[make_adapter_input] Train data size:")
    print(f"input_ids: {train_input_ids.shape}, attention_mask: {train_attention_mask.shape}, "
          f"token_type_ids: {train_token_type_ids.shape}")

    dev_input_ids = np.array(input_ids_list[train_size:dev_size])
    dev_attention_mask = np.array(attention_mask_list[train_size:dev_size])
    dev_token_type_ids = np.array(token_type_ids_list[train_size:dev_size])
    print("[make_adapter_input] Dev data size:")
    print(f"input_ids: {dev_input_ids.shape}, attention_mask: {dev_attention_mask.shape}, "
          f"token_type_ids: {dev_token_type_ids.shape}")

    test_input_ids = np.array(input_ids_list[dev_size:])
    test_attention_mask = np.array(attention_mask_list[dev_size:])
    test_token_type_ids = np.array(token_type_ids_list[dev_size:])
    print("[make_adapter_input] Test data size:")
    print(f"input_ids: {test_input_ids.shape}, attention_mask: {test_attention_mask.shape}, "
          f"token_type_ids: {test_token_type_ids.shape}")

    # Save
    save_dir = "../corpus/npy/adapter/"
    mode_list = ["train", "dev", "test"]
    save_input_ids = [train_input_ids, dev_input_ids, test_input_ids]
    save_attention_mask = [train_attention_mask, dev_attention_mask, test_attention_mask]
    save_token_type_ids = [train_token_type_ids, dev_token_type_ids, test_token_type_ids]

    for mode, save_data in zip(mode_list, save_input_ids):
        np.save(save_dir+mode+"_input_ids", save_data)
    for mode, save_data in zip(mode_list, save_attention_mask):
        np.save(save_dir+mode+"_attention_mask", save_data)
    for mode, save_data in zip(mode_list, save_token_type_ids):
        np.save(save_dir+mode+"_token_type_ids", save_data)
    print("[make_adapter_input] Save Complete !")

#=======================================================================================
def make_span_morp_aware_npy(tokenizer_name: str, src_list: List[Sentence],
                             seq_max_len: int = 128, debug_mode: bool = False,
                             span_max_len: int = 10, save_npy_path: str = None,
                             target_n_pos: int = 14, target_tag_list: List = [],
                             train_data_ratio: int = 7
                             ):
#=======================================================================================
    span_minus = int((span_max_len + 1) * span_max_len / 2)
    max_num_span = int(seq_max_len * span_max_len - span_minus)

    npy_dict = {
        "input_ids": [],
        "label_ids": [],
        "attention_mask": [],
        "token_type_ids": [],
        "all_span_len_list": [],
        "real_span_mask_token": [],
        "span_only_label_token": [],
        "all_span_idx_list": [],

        "pos_ids": []
    }

    # shuffle
    random.shuffle(src_list)

    # Init
    etri_tags = {'O': 0, 'FD': 1, 'EV': 2, 'DT': 3, 'TI': 4, 'MT': 5,
                 'AM': 6, 'LC': 7, 'CV': 8, 'PS': 9, 'TR': 10,
                 'TM': 11, 'AF': 12, 'PT': 13, 'OG': 14, 'QT': 15}
    ne_ids2tag = {v: i for i, v in enumerate(etri_tags)}
    ne_detail_ids2_tok = {v: k for k, v in ETRI_TAG.items()}
    print(ne_ids2tag)

    mecab = Mecab()
    tokenizer = ElectraTokenizer.from_pretrained(tokenizer_name)

    # For K-Adapter
    # if b_make_adapter_input:
    #     make_adapter_input(src_list=src_list, tokenizer=tokenizer, max_length=seq_max_len)
    #     return

    total_tok_cnt = 0
    unk_tok_cnt = 0 # [UNK] 나오는거 Count
    total_data_size = 0
    for proc_idx, src_item in enumerate(src_list):
        # 데이터 필터링
        if 0 == len(src_item.ne_list) and 3 >= len(src_item.word_list):
            continue

        if 0 == (proc_idx % 1000):
            print(f"{proc_idx} Processing... {src_item.text}")

        if debug_mode:
            is_test_str = False
            for test_str in test_str_list:
                if test_str in src_item.text:
                    is_test_str = True
            if not is_test_str:
                continue
        total_data_size += 1

        # Mecab
        mecab_res = mecab.pos(src_item.text)
        # [('전창수', 'NNP', False), ('(', 'SSO', False), ('42', 'SN', False)]
        conv_mecab_res = convert_morp_connected_tokens(mecab_res, src_text=src_item.text)
        print(mecab_res)
        print(conv_mecab_res)
        input()

        origin_tokens = []
        text_tokens = []
        token_pos_list = []
        for m_idx, mecab_item in enumerate(conv_mecab_res):
            tokens = tokenizer.tokenize(mecab_item[0])
            origin_tokens.extend(tokens)

            if mecab_item[-1]:
                for tok in tokens:
                    text_tokens.append("##"+tok)
            else:
                text_tokens.extend(tokens)

            # 0 index에는 [CLS] 토큰이 있어야 한다.
            for _ in range(len(tokens)):
                token_pos_list.append(mecab_item[1].split("+"))

        origin_token_ids = tokenizer.convert_tokens_to_ids(origin_tokens)
        conv_token_ids = tokenizer.convert_tokens_to_ids(text_tokens)
        for tok_idx, (ori_tok, conv_tok) in enumerate(zip(origin_token_ids, conv_token_ids)):
            if 1 == conv_tok and 1 != ori_tok:
                text_tokens[tok_idx] = origin_tokens[tok_idx]

        # morp_ids
        mecab_type_len = len(MECAB_POS_TAG.keys())
        mecab_tag2id = {v: k for k, v in MECAB_POS_TAG.items()}
        pos_ids = [[]] # [CLS]
        for tok_pos in token_pos_list:
            curr_pos = []
            # curr_add_idx = 1
            for pos in tok_pos:
                filter_pos = pos if "UNKNOWN" != pos and "NA" != pos and "UNA" != pos and "VSV" != pos else "O"
                # pos_idx = mecab_tag2id[filter_pos]
                curr_pos.append(mecab_tag2id[filter_pos])
                # curr_add_idx += 1
            pos_ids.append(curr_pos)

        if seq_max_len <= len(pos_ids):
            pos_ids = pos_ids[:seq_max_len - 1]
            pos_ids.append([0 for _ in range(mecab_type_len)]) # [SEP]
        else:
            pos_ids_size = len(pos_ids)
            for _ in range(seq_max_len - pos_ids_size):
                pos_ids.append([0 for _ in range(mecab_type_len)])

        # Text Tokens
        valid_token_len = 0
        text_tokens.insert(0, "[CLS]")
        if seq_max_len <= len(text_tokens):
            text_tokens = text_tokens[:seq_max_len - 1]
            text_tokens.append("[SEP]")

            valid_token_len = seq_max_len
        else:
            text_tokens.append("[SEP]")
            valid_token_len = len(text_tokens)
        
        # NE - Token 단위
        label_ids = [ETRI_TAG["O"]] * len(text_tokens)
        b_check_use = [False for _ in range(len(text_tokens))]
        for ne_idx, ne_item in enumerate(src_item.ne_list):
            ne_char_list = list(ne_item.text.replace(" ", ""))
            concat_item_list = []
            for tok_idx in range(len(text_tokens)):
                if b_check_use[tok_idx]:
                    continue
                for sub_idx in range(tok_idx + 1, len(text_tokens)):
                    concat_word = ["".join(x).replace("##", "") for x in text_tokens[tok_idx:sub_idx]]
                    concat_item_list.append(("".join(concat_word), (tok_idx, sub_idx)))
            concat_item_list = [x for x in concat_item_list if "".join(ne_char_list) in x[0]]
            concat_item_list.sort(key=lambda x: len(x[0]))
            if 0 >= len(concat_item_list):
                continue
            target_idx_pair = concat_item_list[0][1]

            for bio_idx in range(target_idx_pair[0], target_idx_pair[1]):
                b_check_use[bio_idx] = True
                if bio_idx == target_idx_pair[0]:
                    label_ids[bio_idx] = ETRI_TAG["B-" + ne_item.type]
                else:
                    label_ids[bio_idx] = ETRI_TAG["I-" + ne_item.type]

        if seq_max_len <= len(label_ids):
            label_ids = label_ids[:seq_max_len - 1]
            label_ids.append(ETRI_TAG["O"])
        else:
            label_ids_size = len(label_ids)
            for _ in range(seq_max_len - label_ids_size):
                label_ids.append(ETRI_TAG["O"])

        # Span NER
        # context_split = [x[0] for x in mecab_res]
        all_span_idx_list = enumerate_spans(text_tokens, offset=0, max_span_width=span_max_len)
        all_span_len_list = []
        for idx_pair in all_span_idx_list:
            s_idx, e_idx = idx_pair
            span_len = e_idx - s_idx + 1
            all_span_len_list.append(span_len)

        span_idx_label_dict = make_span_idx_label_pair(src_item.ne_list, text_tokens)
        span_idx_new_label_dict = convert2tokenIdx(span_idxLab=span_idx_label_dict,
                                                   all_span_idxs=all_span_idx_list)
        span_only_label_token = [] # 만들어진 span 집합들의 label
        for idx_str, label in span_idx_new_label_dict.items():
            span_only_label_token.append(ne_ids2tag[label])

        text_tokens += ["[PAD]"] * (seq_max_len - valid_token_len)
        input_ids = tokenizer.convert_tokens_to_ids(text_tokens)
        attention_mask = ([1] * valid_token_len) + ([0] * (seq_max_len - valid_token_len))
        token_type_ids = [0] * seq_max_len

        # TEST - UNK 세보기
        for tok in input_ids:
            total_tok_cnt += 1
            if 1 == tok:
                unk_tok_cnt += 1

        # Span Len
        all_span_idx_list = all_span_idx_list[:max_num_span]
        span_only_label_token = span_only_label_token[:max_num_span]
        all_span_len_list = all_span_len_list[:max_num_span]
        real_span_mask_token = np.ones_like(span_only_label_token).tolist()

        ''' 모델에서 POS Embedding 만드는거 속도 느려서 미리 전처리 '''
        mecab_tag2ids = {v: k for k, v in MECAB_POS_TAG.items()}  # origin, 1: "NNG"
        # {1: 0, 2: 1, 43: 2, 3: 3, 5: 4, 4: 5, 16: 6, 17: 7, 18: 8, 19: 9, 20: 10, 23: 11, 24: 12, 21: 13, 22: 14}
        target_tag2ids = {mecab_tag2ids[x]: i for i, x in enumerate(target_tag_list)}
        pos_target_onehot = []
        for start_idx, end_idx in all_span_idx_list:
            span_pos = [0 for _ in range(target_n_pos)]
            for pos in pos_ids[start_idx:end_idx + 1]:
                for pos_item in pos:  # @TODO: Plz Check
                    if pos_item in target_tag2ids.keys():
                        if 14 == target_n_pos:
                            if 0 == pos_item or 1 == pos_item:
                                span_pos[0] = 1
                            else:
                                span_pos[target_tag2ids[pos_item] - 1] = 1
                        else:
                            span_pos[target_tag2ids[pos_item]] = 1
            pos_target_onehot.append(span_pos)
        # end, b_make_only_pos_ids

        '''
            all_span_idx_list와 span_only_label_token을 통해서
            정답 span을 알 수 있다.
            실제적으로 Span을 예측하고 Label을 Return하는 형식으로 output이 나올 것이라
            Span을 text token으로 변환할때 BIO 태깅이 들어가야 할듯.
        '''

        # print(span_only_label_token)
        # print(all_span_len_list)
        # print(real_span_mask_token)
        # print(all_span_idx_list)

        if max_num_span > len(span_only_label_token):
            diff_len = max_num_span - len(span_only_label_token)
            span_only_label_token += [0] * diff_len
        if max_num_span > len(all_span_len_list):
            diff_len = max_num_span - len(all_span_len_list)
            all_span_len_list += [0] * diff_len
        if max_num_span > len(real_span_mask_token):
            diff_len = max_num_span - len(real_span_mask_token)
            real_span_mask_token += [0] * diff_len
        if max_num_span > len(all_span_idx_list):
            diff_len = max_num_span - len(all_span_idx_list)
            all_span_idx_list += [(0, 0)] * diff_len
        if max_num_span > len(pos_target_onehot):
            diff_len = max_num_span - len(pos_target_onehot)
            pos_target_onehot += [[0 for _ in range(target_n_pos)]] * diff_len

        '''span 별 가지는 nn, josa one-hot으로 나타냄'''
        # all_nn_span_onehot, all_josa_span_onehot = make_span_nn_josa_onehot(all_span_idx_list=all_span_idx_list,
        #                                                                     nn_onehot=nn_one_hot_list,
        #                                                                     josa_onehot=josa_one_hot_list)

        assert len(input_ids) == seq_max_len, f"{len(input_ids)}"
        assert len(attention_mask) == seq_max_len, f"{len(attention_mask)}"
        assert len(token_type_ids) == seq_max_len, f"{len(token_type_ids)}"
        assert len(label_ids) == seq_max_len, f"{len(label_ids)}"
        assert len(pos_ids) == seq_max_len, f"{len(pos_ids)}"

        assert len(span_only_label_token) == max_num_span, f"{len(span_only_label_token)}"
        assert len(all_span_idx_list) == max_num_span, f"{len(all_span_idx_list)}"
        assert len(all_span_len_list) == max_num_span, f"{len(all_span_len_list)}"
        assert len(real_span_mask_token) == max_num_span, f"{len(real_span_mask_token)}"
        assert len(pos_target_onehot) == max_num_span, f"{len(pos_target_onehot)}, {max_num_span}"

        # if not b_make_only_pos_ids:
        npy_dict["input_ids"].append(input_ids)
        npy_dict["attention_mask"].append(attention_mask)
        npy_dict["token_type_ids"].append(token_type_ids)
        npy_dict["label_ids"].append(label_ids)

        npy_dict["span_only_label_token"].append(span_only_label_token)
        npy_dict["all_span_len_list"].append(all_span_len_list)
        npy_dict["real_span_mask_token"].append(real_span_mask_token)
        npy_dict["all_span_idx_list"].append(all_span_idx_list)

        npy_dict["pos_ids"].append(pos_target_onehot)

        if debug_mode:
            print(span_idx_label_dict)
            print(span_idx_new_label_dict)
            print(tokenizer.tokenize(src_item.text))
            for i, (ids, t, l, p) in enumerate(zip(input_ids[1:], text_tokens[1:], label_ids[1:], token_pos_list)):
                if "[PAD]" == t:
                    break
                print(i, t, ne_detail_ids2_tok[l], p)
            input()

            for sp_idx, sp_len, p_t_oh in zip(all_span_idx_list, all_span_len_list, pos_target_onehot):
                print(sp_idx, sp_len, p_t_oh)
            input()

    print("Total Tok Count: ", total_tok_cnt)
    print("[UNK] Count: ", unk_tok_cnt)

    if not debug_mode:
        save_span_npy(npy_dict, total_data_size, save_npy_path, train_data_ratio)

#=======================================================================================
def save_only_pos_ids(npy_dict, src_list_len, save_path):
#=======================================================================================
    npy_dict["pos_ids"] = np.array(npy_dict["pos_ids"])
    print(f"[save_only_pos_ids] pos_ids.shape: {npy_dict['pos_ids'].shape}")

    split_size = int(src_list_len * 0.1)
    train_size = split_size * 7
    dev_size = train_size + split_size

    train_pos_ids_np = npy_dict["pos_ids"][:train_size]
    dev_pos_ids_np = npy_dict["pos_ids"][train_size:dev_size]
    test_pos_ids_np = npy_dict["pos_ids"][dev_size:]

    print(f"train_pos_ids.shape: {train_pos_ids_np.shape}")
    print(f"dev_pos_ids_np.shape: {dev_pos_ids_np.shape}")
    print(f"test_pos_ids_np.shape: {test_pos_ids_np.shape}")

    root_path = "../corpus/npy/" + save_path
    np.save(root_path + "/train_pos_ids", train_pos_ids_np)
    np.save(root_path + "/dev_pos_ids", dev_pos_ids_np)
    np.save(root_path + "/test_pos_ids", test_pos_ids_np)

    print("[save_only_pos_ids] save complete")

#=======================================================================================
def save_span_npy(npy_dict, src_list_len, save_path, train_data_ratio):
#=======================================================================================
    npy_dict["input_ids"] = np.array(npy_dict["input_ids"])
    npy_dict["attention_mask"] = np.array(npy_dict["attention_mask"])
    npy_dict["token_type_ids"] = np.array(npy_dict["token_type_ids"])
    npy_dict["label_ids"] = np.array(npy_dict["label_ids"])

    npy_dict["span_only_label_token"] = np.array(npy_dict["span_only_label_token"])
    npy_dict["all_span_len_list"] = np.array(npy_dict["all_span_len_list"])
    npy_dict["real_span_mask_token"] = np.array(npy_dict["real_span_mask_token"])
    npy_dict["all_span_idx_list"] = np.array(npy_dict["all_span_idx_list"])

    npy_dict["pos_ids"] = np.array(npy_dict["pos_ids"])

    print(f"input_ids.shape: {npy_dict['input_ids'].shape}")
    print(f"attention_mask.shape: {npy_dict['attention_mask'].shape}")
    print(f"token_type_ids.shape: {npy_dict['token_type_ids'].shape}")
    print(f"label_ids.shape: {npy_dict['label_ids'].shape}")

    print(f"span_only_label_token.shape: {npy_dict['span_only_label_token'].shape}")
    print(f"all_span_len_list.shape: {npy_dict['all_span_len_list'].shape}")
    print(f"real_span_mask_token.shape: {npy_dict['real_span_mask_token'].shape}")
    print(f"all_span_idx_list.shape: {npy_dict['all_span_idx_list'].shape}")

    print(f"pos_ids.shape: {npy_dict['pos_ids'].shape}")

    split_size = int(src_list_len * 0.1)
    train_size = split_size * train_data_ratio
    dev_size = train_size + split_size
    print(f"train_data_ratio: {train_data_ratio}")

    # Train
    train_np = [npy_dict["input_ids"][:train_size],
                npy_dict["attention_mask"][:train_size],
                npy_dict["token_type_ids"][:train_size]]
    train_np = np.stack(train_np, axis=-1)
    train_label_ids_np = npy_dict["label_ids"][:train_size]

    train_span_only_label_token_np = npy_dict["span_only_label_token"][:train_size]
    train_all_span_len_list_np = npy_dict["all_span_len_list"][:train_size]
    train_real_span_mask_token_np = npy_dict["real_span_mask_token"][:train_size]
    train_all_span_idx_list_np = npy_dict["all_span_idx_list"][:train_size]

    train_pos_ids_np = npy_dict["pos_ids"][:train_size]

    print(f"train_np.shape: {train_np.shape}")
    print(f"train_label_ids.shape: {train_label_ids_np.shape}")

    print(f"train_span_only_label_token_np.shape: {train_span_only_label_token_np.shape}")
    print(f"train_all_span_len_list_np.shape: {train_all_span_len_list_np.shape}")
    print(f"train_real_span_mask_token_np.shape: {train_real_span_mask_token_np.shape}")
    print(f"train_all_span_idx_list_np.shape: {train_all_span_idx_list_np.shape}")

    print(f"train_pos_ids.shape: {train_pos_ids_np.shape}")

    # Dev
    dev_np = [npy_dict["input_ids"][train_size:dev_size],
              npy_dict["attention_mask"][train_size:dev_size],
              npy_dict["token_type_ids"][train_size:dev_size]
              ]
    dev_np = np.stack(dev_np, axis=-1)
    dev_label_ids_np = npy_dict["label_ids"][train_size:dev_size]

    dev_span_only_label_token_np = npy_dict["span_only_label_token"][train_size:dev_size]
    dev_all_span_len_list_np = npy_dict["all_span_len_list"][train_size:dev_size]
    dev_real_span_mask_token_np = npy_dict["real_span_mask_token"][train_size:dev_size]
    dev_all_span_idx_list_np = npy_dict["all_span_idx_list"][train_size:dev_size]

    dev_pos_ids_np = npy_dict["pos_ids"][train_size:dev_size]

    print(f"dev_np.shape: {dev_np.shape}")
    print(f"dev_label_ids.shape: {dev_label_ids_np.shape}")

    print(f"dev_span_only_label_token_np.shape: {dev_span_only_label_token_np.shape}")
    print(f"dev_all_span_len_list_np.shape: {dev_all_span_len_list_np.shape}")
    print(f"dev_real_span_mask_token_np.shape: {dev_real_span_mask_token_np.shape}")
    print(f"dev_all_span_idx_list_np.shape: {dev_all_span_idx_list_np.shape}")

    print(f"dev_pos_ids_np.shape: {dev_pos_ids_np.shape}")

    # Test
    test_np = [npy_dict["input_ids"][dev_size:],
               npy_dict["attention_mask"][dev_size:],
               npy_dict["token_type_ids"][dev_size:]
              ]
    test_np = np.stack(test_np, axis=-1)
    test_label_ids_np = npy_dict["label_ids"][dev_size:]

    test_span_only_label_token_np = npy_dict["span_only_label_token"][dev_size:]
    test_all_span_len_list_np = npy_dict["all_span_len_list"][dev_size:]
    test_real_span_mask_token_np = npy_dict["real_span_mask_token"][dev_size:]
    test_all_span_idx_list_np = npy_dict["all_span_idx_list"][dev_size:]

    test_pos_ids_np = npy_dict["pos_ids"][dev_size:]

    print(f"test_np.shape: {test_np.shape}")
    print(f"test_label_ids.shape: {test_label_ids_np.shape}")

    print(f"test_span_only_label_token_np.shape: {test_span_only_label_token_np.shape}")
    print(f"test_all_span_len_list_np.shape: {test_all_span_len_list_np.shape}")
    print(f"test_real_span_mask_token_np.shape: {test_real_span_mask_token_np.shape}")
    print(f"test_all_span_idx_list_np.shape: {test_all_span_idx_list_np.shape}")

    print(f"test_pos_ids_np.shape: {test_pos_ids_np.shape}")

    # Save
    root_path = "../corpus/npy/" + save_path
    # save input_ids, attention_mask, token_type_ids
    np.save(root_path + "/train", train_np)
    np.save(root_path + "/dev", dev_np)
    np.save(root_path + "/test", test_np)

    np.save(root_path + "/train_span_only_label_token", train_span_only_label_token_np)
    np.save(root_path + "/dev_span_only_label_token", dev_span_only_label_token_np)
    np.save(root_path + "/test_span_only_label_token", test_span_only_label_token_np)

    np.save(root_path + "/train_all_span_len_list", train_all_span_len_list_np)
    np.save(root_path + "/dev_all_span_len_list", dev_all_span_len_list_np)
    np.save(root_path + "/test_all_span_len_list", test_all_span_len_list_np)

    np.save(root_path + "/train_label_ids", train_label_ids_np)
    np.save(root_path + "/dev_label_ids", dev_label_ids_np)
    np.save(root_path + "/test_label_ids", test_label_ids_np)

    np.save(root_path + "/train_real_span_mask_token", train_real_span_mask_token_np)
    np.save(root_path + "/dev_real_span_mask_token", dev_real_span_mask_token_np)
    np.save(root_path + "/test_real_span_mask_token", test_real_span_mask_token_np)

    np.save(root_path + "/train_all_span_idx", train_all_span_idx_list_np)
    np.save(root_path + "/dev_all_span_idx", dev_all_span_idx_list_np)
    np.save(root_path + "/test_all_span_idx", test_all_span_idx_list_np)

    np.save(root_path + "/train_pos_ids", train_pos_ids_np)
    np.save(root_path + "/dev_pos_ids", dev_pos_ids_np)
    np.save(root_path + "/test_pos_ids", test_pos_ids_np)

    print("save complete")

#=======================================================================================
def make_span_char_npy(
        tokenizer_name: str, src_list: List[Sentence],
        seq_max_len: int = 128, debug_mode: bool = False,
        span_max_len: int = 8, save_npy_path: str = None,
        target_n_pos: int = 14, target_tag_list: List = [],
        train_data_ratio: int = 8
):
#=======================================================================================
    print(f"target_n_pos: {target_n_pos}")
    print(f"target_tag_list: {target_tag_list}")
    print(f"train_data_ratio: {train_data_ratio}")
    print(f"span_max_len: {span_max_len}")

    span_minus = int((span_max_len + 1) * span_max_len / 2)
    max_num_span = int(seq_max_len * span_max_len - span_minus)

    npy_dict = {
        "input_ids": [],
        "label_ids": [],
        "attention_mask": [],
        "token_type_ids": [],
        "all_span_len_list": [],
        "real_span_mask_token": [],
        "span_only_label_token": [],
        "all_span_idx_list": [],

        "pos_ids": []
    }

    # shuffle
    random.shuffle(src_list)

    # init
    etri_tags = {
        'O': 0, 'FD': 1, 'EV': 2, 'DT': 3, 'TI': 4, 'MT': 5,
        'AM': 6, 'LC': 7, 'CV': 8, 'PS': 9, 'TR': 10,
        'TM': 11, 'AF': 12, 'PT': 13, 'OG': 14, 'QT': 15
    }
    ne_ids2tag = {v: i for i, v in enumerate(etri_tags)}
    ne_detail_ids2_tok = {v: k for k, v in ETRI_TAG.items()}
    print(ne_ids2tag)

    mecab = Mecab()
    tokenizer = KoCharElectraTokenizer.from_pretrained(tokenizer_name)

    total_tok_cnt = 0
    unk_tok_cnt = 0 # [UNK] 나오는거 Count
    total_data_size = 0
    for proc_idx, src_item in enumerate(src_list):
        # 데이터 필터링
        if 0 == len(src_item.ne_list) and 3 >= len(src_item.word_list):
            continue

        if 0 == (proc_idx % 1000):
            print(f"{proc_idx} Processing... {src_item.text}")

        if debug_mode:
            is_test_str = False
            for test_str in test_str_list:
                if test_str in src_item.text:
                    is_test_str = True
            if not is_test_str:
                continue
        total_data_size += 1

        # MeCab
        mecab_res = mecab.pos(src_item.text)
        # [('전창수', 'NNP', False), ('(', 'SSO', False), ('42', 'SN', False)]
        conv_mecab_res = convert_character_pos_tokens(mecab_res, src_text=src_item.text)
        text_tokens = tokenizer.tokenize(src_item.text)
        text_tokens.insert(0, "[CLS]")

        # pos_ids
        mecab_tag2id = {v: k for k, v in MECAB_POS_TAG.items()}
        pos_ids = [(0, 0, [mecab_tag2id["O"]])] # [CLS] -> (start_index, end_index, POS)
        pos_start_idx = 1
        for tok_pos in conv_mecab_res:
            curr_pos = []
            for pos in tok_pos[1]:
                filter_pos = pos if "UNKNOWN" != pos and "NA" != pos and "UNA" != pos and "VSV" != pos else "O"
                curr_pos.append(mecab_tag2id[filter_pos])
            end_index = pos_start_idx+len(tok_pos[0]) - 1
            if " " == tok_pos[0]:
                end_index = pos_start_idx
            pos_ids.append((pos_start_idx, end_index, curr_pos))
            pos_start_idx = end_index + 1

        if seq_max_len <= len(pos_ids):
            pos_ids = pos_ids[:seq_max_len - 1]
            pos_ids.append((127, 127, [mecab_tag2id["O"]]))
        else:
            last_pos_idx = pos_ids[-1][1]
            for empty_idx in range(last_pos_idx + 1, seq_max_len):
                pos_ids.append((empty_idx, empty_idx, [mecab_tag2id["O"]]))

        # Text Tokens
        valid_token_len = 0
        if seq_max_len <= len(text_tokens):
            text_tokens = text_tokens[:seq_max_len - 1]
            text_tokens.append("[SEP]")

            valid_token_len = seq_max_len
        else:
            text_tokens.append("[SEP]")
            valid_token_len = len(text_tokens)

        # Label_ids
        label_ids = [ETRI_TAG["O"]] * len(text_tokens)
        b_check_use = [False for _ in range(len(text_tokens))]
        for ne_idx, ne_item in enumerate(src_item.ne_list):
            # ne_char_list = list(ne_item.text.replace(" ", ""))
            ne_char_list = list(ne_item.text)
            concat_item_list = []
            for tok_idx in range(len(text_tokens)):
                if b_check_use[tok_idx]:
                    continue
                for sub_idx in range(tok_idx + 1, len(text_tokens)):
                    # concat_word = ["".join(x).replace("##", "") for x in text_tokens[tok_idx:sub_idx]]
                    concat_word = ["".join(x) for x in text_tokens[tok_idx:sub_idx]]
                    concat_item_list.append(("".join(concat_word), (tok_idx, sub_idx)))
            concat_item_list = [x for x in concat_item_list if "".join(ne_char_list) in x[0]]
            concat_item_list.sort(key=lambda x: len(x[0]))
            if 0 >= len(concat_item_list):
                continue
            target_idx_pair = concat_item_list[0][1]

            for bio_idx in range(target_idx_pair[0], target_idx_pair[1]):
                b_check_use[bio_idx] = True
                if bio_idx == target_idx_pair[0]:
                    label_ids[bio_idx] = ETRI_TAG["B-" + ne_item.type]
                else:
                    label_ids[bio_idx] = ETRI_TAG["I-" + ne_item.type]

        if seq_max_len <= len(label_ids):
            label_ids = label_ids[:seq_max_len - 1]
            label_ids.append(ETRI_TAG["O"])
        else:
            label_ids_size = len(label_ids)
            for _ in range(seq_max_len - label_ids_size):
                label_ids.append(ETRI_TAG["O"])

        all_span_idx_list = enumerate_spans(text_tokens, offset=0, max_span_width=span_max_len)
        all_span_len_list = []
        for idx_pair in all_span_idx_list:
            s_idx, e_idx = idx_pair
            span_len = e_idx - s_idx + 1
            all_span_len_list.append(span_len)

        span_idx_label_dict = make_span_idx_label_pair(src_item.ne_list, text_tokens)
        span_idx_new_label_dict = convert2tokenIdx(span_idxLab=span_idx_label_dict,
                                                   all_span_idxs=all_span_idx_list)
        span_only_label_token = []  # 만들어진 span 집합들의 label
        for idx_str, label in span_idx_new_label_dict.items():
            span_only_label_token.append(ne_ids2tag[label])

        text_tokens += ["[PAD]"] * (seq_max_len - valid_token_len)
        input_ids = tokenizer.convert_tokens_to_ids(text_tokens)
        attention_mask = ([1] * valid_token_len) + ([0] * (seq_max_len - valid_token_len))
        token_type_ids = [0] * seq_max_len

        # TEST - UNK 세보기
        for tok in input_ids:
            total_tok_cnt += 1
            if 1 == tok:
                unk_tok_cnt += 1

        # Span Len
        all_span_idx_list = all_span_idx_list[:max_num_span]
        span_only_label_token = span_only_label_token[:max_num_span]
        all_span_len_list = all_span_len_list[:max_num_span]
        real_span_mask_token = np.ones_like(span_only_label_token).tolist()

        # print(span_only_label_token)
        # print(all_span_len_list)
        # print(real_span_mask_token)
        # print(all_span_idx_list)

        ''' 모델에서 POS Embedding 만드는거 속도 느려서 미리 전처리 '''
        mecab_tag2ids = {v: k for k, v in MECAB_POS_TAG.items()}  # origin, 1: "NNG"
        # {1: 0, 2: 1, 43: 2, 3: 3, 5: 4, 4: 5, 16: 6, 17: 7, 18: 8, 19: 9, 20: 10, 23: 11, 24: 12, 21: 13, 22: 14}
        target_tag2ids = {mecab_tag2ids[x]: i for i, x in enumerate(target_tag_list)}
        pos_target_onehot = []
        for start_idx, end_idx in all_span_idx_list:
            span_pos = [0 for _ in range(target_n_pos)]

            for pos_item in pos_ids:
                pos_s_idx = pos_item[0] # Start Index
                pos_e_idx = pos_item[1] # End Index
                pos_info = pos_item[2]  # POS Ids

                if (start_idx <= pos_s_idx) and (end_idx >= pos_e_idx):
                    for pos_i in pos_info:
                        if pos_i in target_tag2ids.keys():
                            if 14 == target_n_pos:
                                if 0 == pos_i or 1 == pos_i:
                                    span_pos[0] = 1
                                else:
                                    span_pos[target_tag2ids[pos_i] - 1] = 1
                            else:
                                span_pos[target_tag2ids[pos_i]] = 1
                else:
                    continue
            pos_target_onehot.append(span_pos)
        # end, b_make_only_pos_ids

        if max_num_span > len(span_only_label_token):
            diff_len = max_num_span - len(span_only_label_token)
            span_only_label_token += [0] * diff_len
        if max_num_span > len(all_span_len_list):
            diff_len = max_num_span - len(all_span_len_list)
            all_span_len_list += [0] * diff_len
        if max_num_span > len(real_span_mask_token):
            diff_len = max_num_span - len(real_span_mask_token)
            real_span_mask_token += [0] * diff_len
        if max_num_span > len(all_span_idx_list):
            diff_len = max_num_span - len(all_span_idx_list)
            all_span_idx_list += [(0, 0)] * diff_len
        if max_num_span > len(pos_target_onehot):
            diff_len = max_num_span - len(pos_target_onehot)
            pos_target_onehot += [[0 for _ in range(target_n_pos)]] * diff_len

        assert len(input_ids) == seq_max_len, f"{len(input_ids)}"
        assert len(attention_mask) == seq_max_len, f"{len(attention_mask)}"
        assert len(token_type_ids) == seq_max_len, f"{len(token_type_ids)}"
        assert len(label_ids) == seq_max_len, f"{len(label_ids)}"
        # assert len(pos_ids) == seq_max_len, f"{len(pos_ids)}"

        assert len(span_only_label_token) == max_num_span, f"{len(span_only_label_token)}"
        assert len(all_span_idx_list) == max_num_span, f"{len(all_span_idx_list)}"
        assert len(all_span_len_list) == max_num_span, f"{len(all_span_len_list)}"
        assert len(real_span_mask_token) == max_num_span, f"{len(real_span_mask_token)}"
        assert len(pos_target_onehot) == max_num_span, f"{len(pos_target_onehot)}, {max_num_span}"

        npy_dict["input_ids"].append(input_ids)
        npy_dict["attention_mask"].append(attention_mask)
        npy_dict["token_type_ids"].append(token_type_ids)
        npy_dict["label_ids"].append(label_ids)

        npy_dict["span_only_label_token"].append(span_only_label_token)
        npy_dict["all_span_len_list"].append(all_span_len_list)
        npy_dict["real_span_mask_token"].append(real_span_mask_token)
        npy_dict["all_span_idx_list"].append(all_span_idx_list)

        npy_dict["pos_ids"].append(pos_target_onehot)

        if debug_mode:
            print(span_idx_label_dict)
            print(span_idx_new_label_dict)
            print(tokenizer.tokenize(src_item.text))
            print(f"NE_items: {src_item.ne_list}")
            for i, (ids, t, l) in enumerate(zip(input_ids, text_tokens, label_ids)):
                if "[PAD]" == t:
                    break
                print(i, t, ne_detail_ids2_tok[l])
            input()

            for sp_idx, sp_len, p_t_oh in zip(all_span_idx_list, all_span_len_list, pos_target_onehot):
                print(sp_idx, sp_len, p_t_oh)
            input()

    print("Total Tok Count: ", total_tok_cnt)
    print("[UNK] Count: ", unk_tok_cnt)

    if not debug_mode:
        save_span_npy(npy_dict, total_data_size, save_npy_path, train_data_ratio)
#=======================================================================================
def make_span_wordpiece_npy(
        tokenizer_name: str, src_list: List[Sentence],
        seq_max_len: int = 128, debug_mode: bool = False,
        span_max_len: int = 8, save_npy_path: str = None,
        target_n_pos: int = 14, target_tag_list: List = [],
        train_data_ratio: int = 7
):
#=======================================================================================
    print(f"target_n_pos: {target_n_pos}")
    print(f"target_tag_list: {target_tag_list}")
    print(f"train_data_ratio: {train_data_ratio}")
    print(f"span_max_len: {span_max_len}")

    span_minus = int((span_max_len + 1) * span_max_len / 2)
    max_num_span = int(seq_max_len * span_max_len - span_minus)

    npy_dict = {
            "input_ids": [],
            "label_ids": [],
            "attention_mask": [],
            "token_type_ids": [],
            "all_span_len_list": [],
            "real_span_mask_token": [],
            "span_only_label_token": [],
            "all_span_idx_list": [],

            "pos_ids": []
        }

    # shuffle
    random.shuffle(src_list)

    # init
    etri_tags = {
        'O': 0, 'FD': 1, 'EV': 2, 'DT': 3, 'TI': 4, 'MT': 5,
        'AM': 6, 'LC': 7, 'CV': 8, 'PS': 9, 'TR': 10,
        'TM': 11, 'AF': 12, 'PT': 13, 'OG': 14, 'QT': 15
    }
    ne_ids2tag = {v: i for i, v in enumerate(etri_tags)}
    ne_detail_ids2_tok = {v: k for k, v in ETRI_TAG.items()}
    print(ne_ids2tag)

    mecab = Mecab()
    tokenizer = ElectraTokenizer.from_pretrained(tokenizer_name)

    total_tok_cnt = 0
    unk_tok_cnt = 0 # [UNK] 나오는거 Count
    total_data_size = 0
    for proc_idx, src_item in enumerate(src_list):
        # 데이터 필터링
        if 0 == len(src_item.ne_list) and 3 >= len(src_item.word_list):
            continue

        if 0 == (proc_idx % 1000):
            print(f"{proc_idx} Processing... {src_item.text}")

        if debug_mode:
            is_test_str = False
            for test_str in test_str_list:
                if test_str in src_item.text:
                    is_test_str = True
            if not is_test_str:
                continue
        total_data_size += 1

        # MeCab
        mecab_res = mecab.pos(src_item.text)
        # [('전창수', 'NNP', False), ('(', 'SSO', False), ('42', 'SN', False)]
        conv_mecab_res = convert_wordpiece_pos_tokens(mecab_res, src_text=src_item.text)
        text_tokens = tokenizer.tokenize(src_item.text)
        text_tokens.insert(0, "[CLS]")

        # pos_ids
        mecab_tag2id = {v: k for k, v in MECAB_POS_TAG.items()}
        mecab_id2tag = {k: v for k, v in MECAB_POS_TAG.items()}
        pos_ids = [(0, 0, [mecab_tag2id["O"]])]  # [CLS] -> (start_index, end_index, POS)
        b_check_pos_use = [False for _ in range(len(text_tokens))]
        for tok_pos in conv_mecab_res:
            curr_pos = []
            for pos in tok_pos[1]:
                filter_pos = pos if "UNKNOWN" != pos and "NA" != pos and "UNA" != pos and "VSV" != pos else "O"
                curr_pos.append(mecab_tag2id[filter_pos])

            for root_idx in range(1, len(text_tokens)):
                if b_check_pos_use[root_idx]:
                    continue
                concat_item_list = []
                for tok_idx in range(root_idx, len(text_tokens)):
                    if b_check_pos_use[tok_idx]:
                        continue
                    for sub_idx in range(tok_idx, len(text_tokens)):
                        concat_word = ["".join(x).replace("##", "") for x in text_tokens[tok_idx:sub_idx+1]]
                        concat_item_list.append(("".join(concat_word), (tok_idx, sub_idx)))
                concat_item_list = [x for x in concat_item_list if tok_pos[0] in x[0]]
                if 0 >= len(concat_item_list):
                    continue
                concat_item_list.sort(key=lambda x: len(x[0]))
                target_idx_pair = concat_item_list[0][1]
                b_check_pos_use[target_idx_pair[0]] = b_check_pos_use[target_idx_pair[1]] = True
                pos_ids.append((target_idx_pair[0], target_idx_pair[1], curr_pos))
                break

        # print(len(text_tokens))
        for i, j, k in pos_ids:
            print(i, j, text_tokens[i], text_tokens[j], [mecab_id2tag[z] for z in k])
        print(pos_ids)

        if seq_max_len <= len(pos_ids):
            pos_ids = pos_ids[:seq_max_len - 1]
            pos_ids.append((127, 127, [mecab_tag2id["O"]]))
        else:
            last_pos_idx = pos_ids[-1][1]
            for empty_idx in range(last_pos_idx + 1, seq_max_len):
                pos_ids.append((empty_idx, empty_idx, [mecab_tag2id["O"]]))

        # Text Tokens
        valid_token_len = 0
        if seq_max_len <= len(text_tokens):
            text_tokens = text_tokens[:seq_max_len - 1]
            text_tokens.append("[SEP]")

            valid_token_len = seq_max_len
        else:
            text_tokens.append("[SEP]")
            valid_token_len = len(text_tokens)

        # Label_ids
        label_ids = [ETRI_TAG["O"]] * len(text_tokens)
        b_check_use = [False for _ in range(len(text_tokens))]
        for ne_idx, ne_item in enumerate(src_item.ne_list):
            ne_char_list = list(ne_item.text.replace(" ", ""))
            concat_item_list = []
            for tok_idx in range(len(text_tokens)):
                if b_check_use[tok_idx]:
                    continue
                for sub_idx in range(tok_idx + 1, len(text_tokens)):
                    concat_word = ["".join(x).replace("##", "") for x in text_tokens[tok_idx:sub_idx]]
                    concat_item_list.append(("".join(concat_word), (tok_idx, sub_idx)))
            concat_item_list = [x for x in concat_item_list if "".join(ne_char_list) in x[0]]
            concat_item_list.sort(key=lambda x: len(x[0]))
            if 0 >= len(concat_item_list):
                continue
            target_idx_pair = concat_item_list[0][1]

            for bio_idx in range(target_idx_pair[0], target_idx_pair[1]):
                b_check_use[bio_idx] = True
                if bio_idx == target_idx_pair[0]:
                    label_ids[bio_idx] = ETRI_TAG["B-" + ne_item.type]
                else:
                    label_ids[bio_idx] = ETRI_TAG["I-" + ne_item.type]

        if seq_max_len <= len(label_ids):
            label_ids = label_ids[:seq_max_len - 1]
            label_ids.append(ETRI_TAG["O"])
        else:
            label_ids_size = len(label_ids)
            for _ in range(seq_max_len - label_ids_size):
                label_ids.append(ETRI_TAG["O"])

        all_span_idx_list = enumerate_spans(text_tokens, offset=0, max_span_width=span_max_len)
        all_span_len_list = []
        for idx_pair in all_span_idx_list:
            s_idx, e_idx = idx_pair
            span_len = e_idx - s_idx + 1
            all_span_len_list.append(span_len)

        span_idx_label_dict = make_span_idx_label_pair(src_item.ne_list, text_tokens)
        span_idx_new_label_dict = convert2tokenIdx(span_idxLab=span_idx_label_dict,
                                                   all_span_idxs=all_span_idx_list)
        span_only_label_token = []  # 만들어진 span 집합들의 label
        for idx_str, label in span_idx_new_label_dict.items():
            span_only_label_token.append(ne_ids2tag[label])

        text_tokens += ["[PAD]"] * (seq_max_len - valid_token_len)
        input_ids = tokenizer.convert_tokens_to_ids(text_tokens)
        attention_mask = ([1] * valid_token_len) + ([0] * (seq_max_len - valid_token_len))
        token_type_ids = [0] * seq_max_len

        # TEST - UNK 세보기
        for tok in input_ids:
            total_tok_cnt += 1
            if 1 == tok:
                unk_tok_cnt += 1

        # Span Len
        all_span_idx_list = all_span_idx_list[:max_num_span]
        span_only_label_token = span_only_label_token[:max_num_span]
        all_span_len_list = all_span_len_list[:max_num_span]
        real_span_mask_token = np.ones_like(span_only_label_token).tolist()

        ''' 모델에서 POS Embedding 만드는거 속도 느려서 미리 전처리 '''
        mecab_tag2ids = {v: k for k, v in MECAB_POS_TAG.items()}  # origin, 1: "NNG"
        # {1: 0, 2: 1, 43: 2, 3: 3, 5: 4, 4: 5, 16: 6, 17: 7, 18: 8, 19: 9, 20: 10, 23: 11, 24: 12, 21: 13, 22: 14}
        target_tag2ids = {mecab_tag2ids[x]: i for i, x in enumerate(target_tag_list)}
        pos_target_onehot = []
        for start_idx, end_idx in all_span_idx_list:
            span_pos = [0 for _ in range(target_n_pos)]

            for pos_item in pos_ids:
                pos_s_idx = pos_item[0]  # Start Index
                pos_e_idx = pos_item[1]  # End Index
                pos_info = pos_item[2]  # POS Ids

                if (start_idx <= pos_s_idx) and (end_idx >= pos_e_idx):
                    for pos_i in pos_info:
                        if pos_i in target_tag2ids.keys():
                            if 14 == target_n_pos:
                                if 0 == pos_i or 1 == pos_i:
                                    span_pos[0] = 1
                                else:
                                    span_pos[target_tag2ids[pos_i] - 1] = 1
                            else:
                                span_pos[target_tag2ids[pos_i]] = 1
                else:
                    continue
            pos_target_onehot.append(span_pos)
        # end, b_make_only_pos_ids

        if max_num_span > len(span_only_label_token):
            diff_len = max_num_span - len(span_only_label_token)
            span_only_label_token += [0] * diff_len
        if max_num_span > len(all_span_len_list):
            diff_len = max_num_span - len(all_span_len_list)
            all_span_len_list += [0] * diff_len
        if max_num_span > len(real_span_mask_token):
            diff_len = max_num_span - len(real_span_mask_token)
            real_span_mask_token += [0] * diff_len
        if max_num_span > len(all_span_idx_list):
            diff_len = max_num_span - len(all_span_idx_list)
            all_span_idx_list += [(0, 0)] * diff_len
        if max_num_span > len(pos_target_onehot):
            diff_len = max_num_span - len(pos_target_onehot)
            pos_target_onehot += [[0 for _ in range(target_n_pos)]] * diff_len

        assert len(input_ids) == seq_max_len, f"{len(input_ids)}"
        assert len(attention_mask) == seq_max_len, f"{len(attention_mask)}"
        assert len(token_type_ids) == seq_max_len, f"{len(token_type_ids)}"
        assert len(label_ids) == seq_max_len, f"{len(label_ids)}"
        # assert len(pos_ids) == seq_max_len, f"{len(pos_ids)}"

        assert len(span_only_label_token) == max_num_span, f"{len(span_only_label_token)}"
        assert len(all_span_idx_list) == max_num_span, f"{len(all_span_idx_list)}"
        assert len(all_span_len_list) == max_num_span, f"{len(all_span_len_list)}"
        assert len(real_span_mask_token) == max_num_span, f"{len(real_span_mask_token)}"
        assert len(pos_target_onehot) == max_num_span, f"{len(pos_target_onehot)}, {max_num_span}"

        npy_dict["input_ids"].append(input_ids)
        npy_dict["attention_mask"].append(attention_mask)
        npy_dict["token_type_ids"].append(token_type_ids)
        npy_dict["label_ids"].append(label_ids)

        npy_dict["span_only_label_token"].append(span_only_label_token)
        npy_dict["all_span_len_list"].append(all_span_len_list)
        npy_dict["real_span_mask_token"].append(real_span_mask_token)
        npy_dict["all_span_idx_list"].append(all_span_idx_list)

        npy_dict["pos_ids"].append(pos_target_onehot)

        if debug_mode:
            print(span_idx_label_dict)
            print(span_idx_new_label_dict)
            print(tokenizer.tokenize(src_item.text))
            print(f"NE_items: {src_item.ne_list}")
            for i, (ids, t, l) in enumerate(zip(input_ids, text_tokens, label_ids)):
                if "[PAD]" == t:
                    break
                print(i, t, ne_detail_ids2_tok[l])
            input()

            for sp_idx, sp_len, p_t_oh in zip(all_span_idx_list, all_span_len_list, pos_target_onehot):
                print(sp_idx, sp_len, p_t_oh, text_tokens[sp_idx[0]:sp_idx[1]+1])
            input()

    if not debug_mode:
        save_span_npy(npy_dict, total_data_size, save_npy_path, train_data_ratio)

### MAIN ###
if "__main__" == __name__:
    # load corpus
    pkl_src_path = "../corpus/pkl/NIKL_ne_pos.pkl"
    all_sent_list = load_ne_entity_list(src_path=pkl_src_path)

    target_n_pos = 14
    target_tag_list = [  # NN은 NNG/NNP 통합
        "NNG", "NNP", "SN", "NNB", "NR", "NNBC",
        "JKS", "JKC", "JKG", "JKO", "JKB", "JX", "JC", "JKV", "JKQ",
    ]
    # target_tag_list = [v for k, v in MECAB_POS_TAG.items() if 0 != k]

    start_time = time.time()
    making_mode = "character"
    if "character" == making_mode:
        tokenizer_name = "monologg/kocharelectra-base-discriminator"
        make_span_char_npy(
            tokenizer_name=tokenizer_name,
            src_list=all_sent_list, seq_max_len=128, span_max_len=8,
            debug_mode=True, save_npy_path="span_ner_char",
            target_n_pos=target_n_pos, target_tag_list=target_tag_list, train_data_ratio=8,
        )
    elif "wordpiece" == making_mode:
        tokenizer_name = "monologg/koelectra-base-v3-discriminator"
        make_span_wordpiece_npy(
            tokenizer_name=tokenizer_name,
            src_list=all_sent_list, seq_max_len=128, span_max_len=8,
            debug_mode=True, save_npy_path="span_ner_wp",
            target_n_pos=target_n_pos, target_tag_list=target_tag_list, train_data_ratio=8,
        )
    elif "morp-aware" == making_mode:
        tokenizer_name = "monologg/koelectra-base-v3-discriminator"
        make_span_morp_aware_npy(
            tokenizer_name=tokenizer_name,
            src_list=all_sent_list, seq_max_len=128, span_max_len=8,
            debug_mode=True, save_npy_path="span_ner",
            target_n_pos=target_n_pos, target_tag_list=target_tag_list, train_data_ratio=8
        )
    else:
        raise Exception(f"Plz Check making mode: {making_mode}")

    print(f"Proc Time: {time.time() - start_time}")