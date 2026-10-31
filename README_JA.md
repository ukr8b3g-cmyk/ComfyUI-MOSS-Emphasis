# ComfyUI-MOSS-Emphasis v0.11.0

[English](README.md) · [方式の違い](#方式の違いを簡単に) · [検証結果](docs/VALIDATION.md) · [参照元](NOTICE.md)

**v0.11.0（Beta）の追加：** 設定に`NegPiPの実装方式 → Forge compatible`を追加しました。全体とUse NegPiPをONにして選択します。保存済みの既存方式は明示的に切り替えるまで維持します。V-Scalingは初期OFF、強度は初期1（0～2）。**OFF／強度0でも基本Forge NegPiPが有効**で、完全無効ではありません。1では画像queryのValueへ符号付き重みを適用し、文章queryは符号だけを読みます。旧通常強度・PPM効果は保持し、この方式では使いません。[リリースノート](docs/RELEASE_NOTES_0.11.0.md)。

Forge方式は、別々の通常CLIP Text Encodeから**PositiveとNegativeの両方**を独立処理します。NegativeはCFGの負側のままで、そこでの`(word:-1)`はPositiveでの負重みと同じ効果ではありません。本体による負側省略は維持します。**MOSS以外は原文の標準処理へ自動バイパス**し、設定を保持してMOSSへ戻すと再び有効になります。既存通常／PPMのモデル対応・Negative処理は変更しません。新方式のLayout JSON・独自chat template・画像参照・加工済み／領域／スケジュール条件は初期対応外です。構造上の未対応配線は実行前に拒否します。

新しいForge由来モジュールはAGPLv3で、既存GPLv3コードと第13条に従って併用します。[NOTICE](NOTICE.md)を参照してください。設定の状態表示に、`/moss_emphasis/source`から**実際の導入版の対応ソースを取得するリンク**を付けています。配置後は本体再起動とブラウザー再読み込みが必要で、CPU検証は実GPUの画質・Kitchen性能・実画面の動作保証ではありません。

**Settings → MOSS Emphasis**で、通常の重み付けと**NegPiP**を切り替える拡張です。普通の**CLIP Text Encode**を使い、専用ノードをキャンバスへ置く必要はありません。

**従来の通常／PPM方式は、標準MOSS-Image、SDXL／Illustrious、標準Animaの3系統に対応**します。自動判定モードでは、**それ以外のモデルは本拡張を自動で無効化（バイパス）**し、標準処理で生成を続けます。Qwen-Image・FLUX・SD1.5・SD3・Krea2・SDXL Refinerなども対象です。Forge方式は標準MOSSのみ対応します。CPU検証段階の試験版で、GPU画質・速度・VRAMは未検証です。

**互換性：** 0.10.1で追加した数値保護は維持します。起動中の旧バックエンドが対応設定（Forgeのschema 4やversion 0.11.0を含む）を拒否した場合、日本語／英語の再起動案内を表示し、生成投入と設定変更を行いません。0.9.0・0.9.1・0.10.0・0.10.1の保存設定は、方式・強さ・対象モデル範囲を保って読み込めます。先行ローカル版のForge設定も引き継ぎます。

## インストール・更新

ComfyUIの `custom_nodes` 内で実行します。

```sh
git clone https://github.com/ukr8b3g-cmyk/ComfyUI-MOSS-Emphasis.git
```

既存導入先は更新後、**ComfyUI本体を再起動してからブラウザーを再読み込み**してください。画面更新だけではPython側は更新されません。追加pip依存・PPM／KJNodesの導入・モデルのダウンロードは不要です。対象モデルの標準対応とV3ノードAPIを備えるComfyUIが必要です。検証版は[検証結果](docs/VALIDATION.md)に記載しています。

## 使い方と切り替え

通常のMODEL・Positive・Negativeの配線を維持し、設定 → MOSS Emphasisを開きます。

| 設定 | 意味 |
|---|---|
| プロンプトの重み付けを有効化 | 全体のON/OFF。ワークフロー単位で保存。新規はOFF |
| 重み付け強度 | 通常方式専用。0～4、開始値は1 |
| NegPiP方式を使用 | OFFで通常方式、ONで選択したNegPiP方式。重ね掛けはしない |
| NegPiPの実装方式 | `PPM reference`は従来方式、`Forge compatible`は新しいMOSS専用方式。初期値はPPM |
| NegPiP効果 | PPM専用。0～1、開始値は1。Forgeでは使わない |
| V-Scalingを使用 | Forge専用。初期OFF。OFFでも基本Forge NegPiPは有効 |
| V-Scaling強度 | ForgeでV-Scaling ON時に使用。0～2、初期値は1。0は基本NegPiPで、無効化ではない |
| 現在の方式 | 選択方式と実効強度を表示。ForgeではMOSS以外の自動バイパスも案内 |

**MODELとCLIPの実際の型から自動判定**します。モデル名での判定や手動モデル選択はありません。全体OFFの間はNegPiPだけONにしても無効です。使っていない方式の強さは保存されますが、計算には使いません。

**どの強度を0にするかで意味が変わります。** 詳しくは下の表を参照してください。全体OFFは、どの方式でも本拡張をバイパスします。ただし、**SDXL／Animaが標準で持つプロンプト重みは原文に対して働きます**。「本拡張OFF＝モデル標準の重みまで無効」ではありません。

![旧版MOSS Emphasis設定画面](docs/images/moss-emphasis-settings.webp)

*画像はNegPiP追加前です。現在は「有効化 → 強度 → NegPiP → 実装方式 → PPM効果 → V-Scaling → V-Scaling強度 → 現在の方式」の順です。使用しない項目は値を保持したまま無効表示になります。ComfyUIが日本語ならラベル・マウスオーバーヘルプも日本語になります。保存する設定IDは同じです。*

## 方式の違いを簡単に

どの方式も「この言葉を強く・弱く反映してほしい」と指定するためのものですが、**調整する場所が違います。** そのため、同じ数字でも画像の出方が変わります。MOSSでの違いをイメージで表すと、次のようになります。画像効果を保証する説明ではありません。

| 方式 | わかりやすくいうと |
|---|---|
| 従来の通常方式 | 「この言葉に、もっと注目して」と指示する。注目度や、その言葉の影響力を調整します。 |
| 従来のPPM NegPiP | 効果1を基準に、数字の大きさで注目度を調整し、マイナスなら画像側に渡す影響を反対向きにします。 |
| **Forge・V-Scaling OFF** | AIに渡す「言葉の情報」の強さを調整します。マイナスの重みによる反転も有効です。 |
| **Forge・V-Scaling ON** | 重みの大きさを「絵に反映する側」で調整します。文章側に反映するのは符号だけにします。 |

例えば、`(red hair:1.5)`は「赤い髪を、もう少し強く反映して」という指定です。ForgeのV OFFでは文章の情報を調整し、V ON・強度**1**では、重みの大きさを絵に反映する側へ移します。PPMへ追加効果を重ねるものではなく、別の計算方式への切り替えです。**赤い髪が必ず1.5倍になるわけではなく、新方式が常に優れているとも限りません。**

構文にも違いがあります。Forgeでは数字のない`(red hair)`も強調として扱いますが、従来のMOSS方式では数値指定のない括弧を文字として残します。Forgeは重み付きの区間ごとにトークン化するため、同じプロンプトでも完全に同じ結果になるとは限りません。

### V-ScalingのON・OFF・強度0

| 操作・状態 | 意味 |
|---|---|
| **全体をOFF** | 選択方式や保存された強度にかかわらず、本拡張をバイパスします。 |
| 通常方式の**重み付け強度を0** | 従来の通常方式をバイパスします。 |
| PPMの**NegPiP効果を0** | 従来のPPM方式をバイパスします。 |
| Forgeの**V-ScalingをOFF** | **基本Forge NegPiPは有効なまま**です。数字の大きさを文章の情報へ反映し、負の重みによる反転も行います。保存されたV強度は使いません。 |
| Forgeの**V ON・強度0** | V OFFと同じ基本Forge NegPiPです。**強度0でもNegPiP全体は無効になりません。** |
| Forgeの**V ON・強度1** | 符号付きの重みを、絵に反映する側へ適用します。文章側は符号だけを反映します。比較の開始値であり、最適値と確認された値ではありません。 |

Forgeでは、保存してある従来の通常強度やPPM効果が0でも、それらの値は使いません。また、プロンプト内の`(red hair:0)`は別の指定です。その語句の扱いを変えるもので、拡張全体を無効にする操作でも、語句が必ず画像から消える指定でもありません。

**Negative欄も違います。** 従来の通常／PPM方式はNegativeの標準処理を維持します。Forge方式ではPositive・Negativeの両方を、それぞれの重みで独立処理します。ただしNegativeはCFGの負側のままなので、そこでマイナスを付けても、Positiveでの負重みと同じ意味にはなりません。「マイナス同士で必ず強調に戻る」とも限りません。

比較するときは、プロンプト・seed・モデル・LoRA・サンプラー・steps・CFGを揃え、Forgeの**V OFF**と**V ON・強度1**だけを切り替えると違いを見やすくなります。好みの結果を選んでください。Forgeは現在、標準MOSS専用です。他モデルでは重み処理を自動バイパスし、従来の通常／PPMによるSDXL・Illustrious・Anima対応は維持します。GPUでの画質比較は未実施です。

## モデル別の処理

この表は従来の通常／PPM方式の対応範囲です。Forgeは現在、標準MOSSのみ対応し、それ以外は自動でバイパスします。

| モデル | 通常方式 | NegPiP効果1 | 確認範囲 |
|---|---|---|---|
| 標準MOSS-Image Base／SFT | 既存KJ式のValue倍率・Attention bias | PPM参照のlog絶対値bias・Value符号 | 従来の計算を維持、CPU回帰確認 |
| 標準SDXL Base系／Illustrious系 | 標準CLIP-L／Gの重み | 絶対値重み＋Key／Value分離、負の語のValue反転 | 実tokenizer・encoder処理・batch・小さな実AttentionのCPU確認 |
| 標準Anima | Qwenアダプター後のT5トークン重み | T5重みの絶対値＋負の語のValue反転 | 前処理／forward・padding・batch・小さな実AttentionのCPU確認 |
| Qwen-Image・FLUX・SD1.5・SD3・Krea2・SDXL Refinerなど、上記以外すべて | 自動でバイパス | 自動でバイパス | モデル標準の処理で生成を続行 |

自動判定モードでは、未対応モデルの重み付け・Attention変更をスキップし、原文・MODEL・Negativeを標準処理へ渡します。保存済みのON/OFFや方式は書き換えず、対応モデルへ戻すと選択中の方式が再び働きます。スキップはサーバーログに記録します。対応MODELとCLIPの不一致は引き続きエラーです。実行グラフ・Conditioningの対応範囲チェックは残るため、一体型サンプラーなどの未対応配線まで自動対応するものではありません。

ここでのQwen-Imageは画像生成モデルのことです。MOSSやAnimaが文章エンコーダーにQwenを使うこととは別で、エンコーダー名だけで無効にはしません。

Illustriousは標準SDXLの構造として扱います。検証ではIllustrious／Animaのチェックポイント自体はロードしていません。Animaは既存のT5 **tokenizer由来の情報**を使い、T5エンコーダーモデルを追加ロードしません。MODELとCLIPは同じモデル向けの標準ペアを使ってください。

**従来の通常／PPM方式**の対象はPositive内の重みです。Negativeは、元々ある標準の重みも含めて計算上の意味を保ちます。SDXLのPPM NegPiPではKey／Value分離に合わせてNegativeを内部で同一内容の2本へ変換しますが、Negative文をNegPiPで再解釈しません。Forgeによる両欄の処理は上の説明を参照してください。

## 重み・0・1の意味

```text
1girl, (red hair:1.2), (realistic:-5)
```

負の数字を書いただけではNegPiPに切り替わりません。選択中の方式で負の重みとして扱います。プロンプト重みに固定の上下限はありませんが、非有限数・係数のoverflow・使用dtypeで表現できない値はエラーになります。重み付けでoverflowが起こり得る場合は、MOSSのValue乗算・Attention maskの合成・Animaのadapter後の乗算結果も検査し、`INVALID_WEIGHT`で停止します。重みの丸め込みや方式の自動変更は行いません。絶対値を増やしても画像上の抑制が比例するとは限りません。

| 従来の通常／PPM方式で、強度／効果が1のとき | 重み0 | 重み1 |
|---|---|---|
| MOSS通常 | Value倍率0。Keyは残る | 通常の重み |
| MOSSのPPM NegPiP | bias用の絶対値を1e-4へfloor。Value符号は正 | 相対重み1。他トークンとの正規化の影響あり |
| SDXL通常／NegPiP | 空プロンプト基準の埋め込み。NegPiPでも符号は正 | 標準の埋め込み |
| Anima通常／NegPiP | 対応する変換後contextを0倍。NegPiPでも符号は正 | 標準の重み |

どれも「概念が必ず消える」という意味ではありません。`(realistic:1)` は通常重みであり、写実化を特別に強める指定ではありません。

**従来の通常／PPM方式では、構文はモデルで異なります。** MOSSは既存の明示小数構文・普通の括弧の文字扱い・入れ子の積・128グループ／16階層制限・文字位置対応を維持します。Layout JSONでは `summary.caption` と `items[].caption` だけを処理します。SDXL／Animaは**標準tokenizer**の括弧・エスケープ・入れ子・トークン重みを使い、MOSS用JSON保護は適用しません。A1111／Compelの正規化モードでもありません。Forgeは別のOriginal相当構文を使い、Layout JSONは初期対応外です。

SDXL／Animaの通常強度`s`は、重み`w`を `1+s*(w-1)` に変換します。NegPiP効果`t`では絶対値重みを `1+t*(abs(w)-1)`、負の語のValue倍率を `1-2*t` とします。効果**1**が固定PPM参照との比較基準で、中間効果は本拡張独自の機能です。**0.5**では負の語のValueが0になりますがトークンは残ります。MOSSでは従来のlog-bias補間です。

## 対応配線・旧設定

通常の `CLIPTextEncode → KSampler / KSamplerAdvanced`、または `CLIPTextEncode → CFGGuider → SamplerCustomAdvanced` に対応します。Text Multiline／CSV／文字列連結から `CLIPTextEncode.text` へ入力できます。通常のLoRA・CLIP skipは標準エンコーダー経路を利用します。

初期対応範囲には `CLIPTextEncodeSDXL`、Advanced CLIP、領域／時間指定／結合Conditioning、ControlNet／IPAdapter、Refiner、独自HFローダー、一体型カスタムサンプラーを含みません。同じ経路の別の重み・attn2置換は二重適用を拒否します。未対応のワークフローではOFFにしてください。

MOSSの制限は従来どおりで、PyTorch/basic、標準の全体Comfy Kitchen INT8 (`--use-ck-attention`) 経路と公式SLGが対象です。Sage／Flash／SOL上書き・層ごとの設定済みINT8は対象外です。実GPUのKitchen／SLG動作は未検証です。SDXL／Animaは標準Attention hookを使い、選択済みカーネルを置き換えません。CPU合格は全GPUバックエンドの保証ではありません。

**schema 1/2の保存済みワークフローは旧MOSS専用動作を維持**します。開いただけでは他モデルの重みを突然有効にしません。新対応を使うには重み設定を明示的に操作（例：全体OFF→ON）して保存してください。状態表示が「旧MOSS方式」から「モデル自動判定」に変わります。診断ログだけでは移行しません。方式やタブを切り替えても両方の強さを保持します。

画面の配線は変更せず、実行グラフのコピーへ内部runtimeを挿入します。設定はジョブごとに固定されキャッシュへ反映されます。グローバルなtokenizer／Attention関数、CFG・サンプラー・スケジューラー・モデルファイル・ComfyUI本体は変更しません。

## API・検証

設定 → MOSS Emphasis → APIエクスポート → **実行用API JSONを書き出す**を使ってください。`/moss_emphasis/prepare` の例は[英語README](README.md#api-and-tests)にあります。prepareの外側形式はversion 1、従来の自動判定設定はschema 3、Forgeはschema 4です。準備エラー時に重みなし生成を投入しません。通常のComfyUI API保存だけでは変換が含まれない場合があります。

```sh
python -m unittest discover -s tests -v
node --test tests/frontend.test.mjs tests/locales.test.mjs
python -B tests/native_contract.py --comfy-root /path/to/ComfyUI
```

[検証結果](docs/VALIDATION.md)では単体テスト・実CPUモジュール・未実施のGPU／画面確認を分けています。既存ファイルはGPL-3.0-only、新しいForge由来モジュールはAGPL-3.0-onlyです。[NOTICE](NOTICE.md)にライセンスの適用範囲と参照元を記載しています。同一画像の完全再現は保証しません。
