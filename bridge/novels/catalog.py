"""Offline curated starter catalogue. Rankings are editorial lists, not live sales charts."""
BOOKS = [
 {"id":"dream-red-mansion","title":"红楼梦","author":"曹雪芹","era":"古代","region":"中国","genre":"世情 / 家族","rank":"经典名著榜","score":100,"cover":"classic","description":"以贾、史、王、薛四大家族的兴衰为背景，描绘大观园中的青春群像与家族命运。","characters":["贾宝玉","林黛玉","薛宝钗","王熙凤","贾探春"]},
 {"id":"journey-west","title":"西游记","author":"吴承恩","era":"古代","region":"中国","genre":"神魔 / 冒险","rank":"经典名著榜","score":98,"cover":"fantasy","description":"唐僧师徒西行取经，在一路的磨难与奇遇中展开神魔世界的冒险。","characters":["孙悟空","唐僧","猪八戒","沙悟净","白骨精"]},
 {"id":"water-margin","title":"水浒传","author":"施耐庵","era":"古代","region":"中国","genre":"英雄 / 江湖","rank":"经典名著榜","score":96,"cover":"hero","description":"群雄因不同际遇聚义梁山，呈现江湖义气、社会秩序与个人命运。","characters":["宋江","林冲","鲁智深","武松","李逵"]},
 {"id":"three-kingdoms","title":"三国演义","author":"罗贯中","era":"古代","region":"中国","genre":"历史 / 权谋","rank":"经典名著榜","score":99,"cover":"history","description":"以东汉末年至三国鼎立为背景，描绘群雄逐鹿、谋略交锋与时代更替。","characters":["诸葛亮","曹操","刘备","关羽","周瑜"]},
 {"id":"liaozhai","title":"聊斋志异","author":"蒲松龄","era":"古代","region":"中国","genre":"志怪 / 爱情","rank":"经典名著榜","score":90,"cover":"mystery","description":"借狐鬼花妖与人间故事映照世情，兼具奇幻想象、爱情悲欢与讽喻。","characters":["聂小倩","宁采臣","婴宁","王子服"]},
 {"id":"peony-pavilion","title":"牡丹亭","author":"汤显祖","era":"古代","region":"中国","genre":"戏曲 / 爱情","rank":"经典名著榜","score":88,"cover":"romance","description":"杜丽娘因梦生情、因情而死又因情复生，书写至情与礼教的冲突。","characters":["杜丽娘","柳梦梅","春香"]},
 {"id":"journey-to-west-modern","title":"长安十二时辰","author":"马伯庸","era":"现代","region":"中国","genre":"历史悬疑","rank":"热门作品榜","score":92,"cover":"history","description":"盛唐长安危机在十二时辰内层层推进，融合悬疑、城市细节与群像叙事。","characters":["张小敬","李必","檀棋"]},
 {"id":"the-three-body-problem","title":"三体","author":"刘慈欣","era":"现代","region":"中国","genre":"科幻","rank":"热门作品榜","score":99,"cover":"scifi","description":"从地球文明与三体文明的接触出发，展开跨越时代的文明冲突与宇宙想象。","characters":["叶文洁","汪淼","罗辑","程心","章北海"]},
 {"id":"to-live","title":"活着","author":"余华","era":"现代","region":"中国","genre":"现实 / 人生","rank":"编辑精选榜","score":95,"cover":"literary","description":"通过福贵一生的起落，呈现普通人在时代变迁中的生存、失去与韧性。","characters":["徐福贵","家珍","凤霞","有庆","二喜"]},
 {"id":"ordinary-world","title":"平凡的世界","author":"路遥","era":"现代","region":"中国","genre":"现实 / 成长","rank":"编辑精选榜","score":94,"cover":"literary","description":"以孙少安、孙少平兄弟的人生道路为线索，描写改革年代普通人的奋斗与选择。","characters":["孙少平","孙少安","田晓霞","田润叶","贺秀莲"]},
 {"id":"four-generations","title":"四世同堂","author":"老舍","era":"现代","region":"中国","genre":"现实 / 家族","rank":"经典名著榜","score":91,"cover":"literary","description":"以北平小羊圈胡同为缩影，描绘战时市民生活、家国命运与人性抉择。","characters":["祁老人","祁瑞宣","祁瑞丰","钱默吟"]},
 {"id":"the-golden-age","title":"黄金时代","author":"王小波","era":"现代","region":"中国","genre":"文学 / 黑色幽默","rank":"编辑精选榜","score":87,"cover":"literary","description":"以独特的叙述声音讨论个体、自由、荒诞与时代经验。","characters":["王二","陈清扬"]},
 {"id":"harry-potter","title":"哈利·波特与魔法石","author":"J.K.罗琳","era":"现代","region":"英国","genre":"奇幻 / 成长","rank":"热门作品榜","score":99,"cover":"fantasy","description":"孤儿哈利收到霍格沃茨录取通知，进入魔法世界并结识伙伴、面对未知。","characters":["哈利·波特","赫敏·格兰杰","罗恩·韦斯莱","阿不思·邓布利多","伏地魔"]},
 {"id":"pride-prejudice","title":"傲慢与偏见","author":"简·奥斯汀","era":"古典","region":"英国","genre":"爱情 / 社会","rank":"经典名著榜","score":98,"cover":"romance","description":"伊丽莎白与达西在误解、偏见和社会礼法中重新认识彼此。","characters":["伊丽莎白·班纳特","达西先生","简·班纳特","宾利先生"]},
 {"id":"jane-eyre","title":"简·爱","author":"夏洛蒂·勃朗特","era":"古典","region":"英国","genre":"爱情 / 成长","rank":"经典名著榜","score":96,"cover":"romance","description":"简·爱在孤独与不平等中坚持自尊，追寻独立、爱情与精神平等。","characters":["简·爱","爱德华·费尔法克斯·罗切斯特","圣约翰·里弗斯"]},
 {"id":"les-miserables","title":"悲惨世界","author":"维克多·雨果","era":"古典","region":"法国","genre":"社会 / 历史","rank":"经典名著榜","score":97,"cover":"history","description":"围绕冉阿让的救赎之路，展开关于法律、良知、贫困与革命的宏大叙事。","characters":["冉阿让","沙威","芳汀","珂赛特","马吕斯"]},
 {"id":"the-little-prince","title":"小王子","author":"安托万·德·圣-埃克苏佩里","era":"现代","region":"法国","genre":"寓言 / 哲思","rank":"经典名著榜","score":95,"cover":"fantasy","description":"飞行员与来自小行星的小王子相遇，以旅程寓言探讨爱、责任与理解。","characters":["小王子","飞行员","玫瑰","狐狸"]},
 {"id":"crime-punishment","title":"罪与罚","author":"陀思妥耶夫斯基","era":"古典","region":"俄罗斯","genre":"心理 / 犯罪","rank":"经典名著榜","score":94,"cover":"mystery","description":"青年拉斯柯尔尼科夫犯罪后的精神煎熬，深入探讨道德、罪责与救赎。","characters":["拉斯柯尔尼科夫","索尼娅","波尔菲里"]},
 {"id":"anna-karenina","title":"安娜·卡列尼娜","author":"列夫·托尔斯泰","era":"古典","region":"俄罗斯","genre":"爱情 / 社会","rank":"经典名著榜","score":96,"cover":"romance","description":"通过安娜与列文两条人生线索，描写爱情、婚姻、家庭与社会伦理。","characters":["安娜·卡列尼娜","列文","吉蒂","渥伦斯基"]},
 {"id":"1984","title":"一九八四","author":"乔治·奥威尔","era":"现代","region":"英国","genre":"反乌托邦 / 科幻","rank":"编辑精选榜","score":97,"cover":"scifi","description":"温斯顿在全面监控与思想控制下寻找真实，呈现权力、语言与自由的寓言。","characters":["温斯顿·史密斯","朱莉娅","奥勃良"]},
 {"id":"dune","title":"沙丘","author":"弗兰克·赫伯特","era":"现代","region":"美国","genre":"科幻 / 政治","rank":"热门作品榜","score":93,"cover":"scifi","description":"保罗·厄崔迪来到沙漠星球厄拉科斯，卷入家族、宗教、生态与帝国权力斗争。","characters":["保罗·厄崔迪","杰西卡夫人","雷托公爵","契妮","弗雷曼人斯第尔格"]},
 {"id":"the-great-gatsby","title":"了不起的盖茨比","author":"F. Scott Fitzgerald","era":"现代","region":"美国","genre":"文学 / 社会","rank":"经典名著榜","score":92,"cover":"literary","description":"爵士时代的浮华派对背后，盖茨比执着追逐爱情与美国梦。","characters":["杰伊·盖茨比","黛西·布坎南","尼克·卡拉威","汤姆·布坎南"]},
 {"id":"sherlock-holmes","title":"福尔摩斯探案集","author":"阿瑟·柯南·道尔","era":"古典","region":"英国","genre":"推理 / 悬疑","rank":"经典名著榜","score":98,"cover":"mystery","description":"伦敦咨询侦探福尔摩斯与华生医生通过观察和演绎破解一系列疑案。","characters":["夏洛克·福尔摩斯","约翰·华生","詹姆斯·莫里亚蒂","艾琳·艾德勒"]},
 {"id":"don-quixote","title":"堂吉诃德","author":"米格尔·德·塞万提斯","era":"古典","region":"西班牙","genre":"讽刺 / 冒险","rank":"经典名著榜","score":93,"cover":"hero","description":"沉迷骑士小说的乡绅踏上游侠之旅，以荒诞经历映照理想与现实。","characters":["堂吉诃德","桑丘·潘沙","杜尔西内娅"]},
 {"id":"one-hundred-years","title":"百年孤独","author":"加夫列尔·加西亚·马尔克斯","era":"现代","region":"哥伦比亚","genre":"魔幻现实 / 家族","rank":"经典名著榜","score":97,"cover":"literary","description":"布恩迪亚家族七代人的兴衰与马孔多的变迁交织成一部魔幻现实主义史诗。","characters":["何塞·阿尔卡蒂奥·布恩迪亚","乌尔苏拉","奥雷里亚诺上校","阿玛兰妲","蕾梅黛丝"]},
 {"id":"norwegian-wood","title":"挪威的森林","author":"村上春树","era":"现代","region":"日本","genre":"青春 / 爱情","rank":"热门作品榜","score":89,"cover":"literary","description":"渡边在青春记忆、失落与亲密关系中寻找自我与生活的方向。","characters":["渡边","直子","绿子","永泽"]},
 {"id":"kafka-shore","title":"海边的卡夫卡","author":"村上春树","era":"现代","region":"日本","genre":"奇幻 / 成长","rank":"编辑精选榜","score":88,"cover":"mystery","description":"少年田村卡夫卡离家出走，与中田等人的命运在现实与超现实之间交错。","characters":["田村卡夫卡","中田","佐伯","星野"]},
 {"id":"kitchen","title":"厨房","author":"吉本芭娜娜","era":"现代","region":"日本","genre":"文学 / 治愈","rank":"编辑精选榜","score":85,"cover":"literary","description":"在失去与相遇之间，人物借由日常生活慢慢修复内心。","characters":["樱井美影","田边雄一","田边绘里子"]},
 {"id":"three-body-remembrance","title":"球状闪电","author":"刘慈欣","era":"现代","region":"中国","genre":"科幻","rank":"编辑精选榜","score":86,"cover":"scifi","description":"从童年目击的球状闪电出发，追寻自然现象背后的科学谜团。","characters":["陈博士","林云","丁仪"]},
 {"id":"the-devotion-of-suspect-x","title":"嫌疑人X的献身","author":"东野圭吾","era":"现代","region":"日本","genre":"推理 / 悬疑","rank":"热门作品榜","score":94,"cover":"mystery","description":"一场精密布局的案件让数学天才与物理学家展开高智商对决。","characters":["石神哲哉","靖子","汤川学","草薙俊平"]},
 {"id":"little-women","title":"小妇人","author":"路易莎·梅·奥尔科特","era":"古典","region":"美国","genre":"家庭 / 成长","rank":"经典名著榜","score":91,"cover":"romance","description":"马奇家的四姐妹在成长、理想与家庭生活中寻找各自的人生道路。","characters":["乔·马奇","梅格·马奇","贝丝·马奇","艾美·马奇","劳里"]},
]

CATEGORIES = ["全部","古代","现代","古典","中国","外国","爱情","奇幻","悬疑","科幻","历史","现实","成长","家族"]
RANKS = ["编辑精选榜","热门作品榜","经典名著榜"]

def list_books(category="全部", rank="全部", q=""):
    rows = list(BOOKS)
    if category and category != "全部":
        rows = [b for b in rows if category in (b["era"], b["region"], b["genre"]) or category in b["genre"]]
        if category == "外国": rows = [b for b in rows if b["region"] != "中国"]
    if rank and rank != "全部": rows = [b for b in rows if b["rank"] == rank]
    q = str(q or "").strip().lower()
    if q: rows = [b for b in rows if q in (b["title"]+b["author"]+b["description"]+" ".join(b["characters"])).lower()]
    return sorted(rows, key=lambda b: (-b["score"], b["title"]))

def get_book(book_id):
    return next((dict(b) for b in BOOKS if b["id"] == book_id), None)
