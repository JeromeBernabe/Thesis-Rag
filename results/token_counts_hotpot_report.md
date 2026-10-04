# Token Count Report: RagTruth (Forced k Values)

**Date:** 2026-09-21 22:10:36

**Total prompts:** 50

**System A:** k=3 (fixed)

**System B:** k=1 (1 prompts), k=2 (39 prompts), k=3 (9 prompts), k=5 (1 prompts)

---

## Aggregate Statistics

| Metric | System A (k=3) | System B (DQN) | Delta |
|--------|----------------|----------------|-------|
| Avg tokens/query | 4029 | 2962 | -1067 (-26.5%) |
| Avg generation time | 2.24s | 0.55s | -1.69s (-75.5%) |
| Avg tokens/sec | 10.9 | 42.7 | +31.8 (+290.4%) |
| Avg GT overlap | 0.051 | 0.060 | +0.009 (+17.8%) |
| Refusal rate | 0/50 (0%) | 0/50 (0%) | +0 |

---

## Per-Prompt Details

### Prompt 1 (ID: 5a76ba1c554299373536018e)

**Question:** The 2001 Intercontinental Cup was a football match played on 27 November 2001, which Ghanaian retired professional footballer, was named as man of the match?

**Ground Truth:** Samuel Osei Kuffour

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Samuel Kuffour. | Samuel Kuffour. |
| Tokens | 3955 | 2673 |
| Prompt tokens | 3948 | 2666 |
| Completion tokens | 7 | 7 |
| Gen time | 2.8665s | 0.1618s |
| Tokens/sec | 2.4 | 43.3 |
| GT overlap | 0.250 | 0.250 |
| Refusal | False | False |

---

### Prompt 2 (ID: 5ae2281e5542994d89d5b37c)

**Question:** Which genus contains more species, Prosopis or Aldrovanda?

**Ground Truth:** Prosopis

| Metric | System A (k=3) | System B (k=5) |
|--------|----------------|----------------|
| Answer | The context does not provide information about the genus Aldrovanda. | There is no information about the genus Aldrovanda in the provided context. |
| Tokens | 3596 | 3854 |
| Prompt tokens | 3582 | 3838 |
| Completion tokens | 14 | 16 |
| Gen time | 1.5051s | 0.4272s |
| Tokens/sec | 9.3 | 37.4 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | True |

---

### Prompt 3 (ID: 5adbd79d5542994650320c00)

**Question:** What is the uprising that began on 22 January 1863 and was the topic of Teodor Żychliński's works?

**Ground Truth:** The January Uprising

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | The uprising that began on 22 January 1863 was the January Uprising. | The January Uprising. |
| Tokens | 4454 | 3000 |
| Prompt tokens | 4436 | 2994 |
| Completion tokens | 18 | 6 |
| Gen time | 1.9492s | 0.1573s |
| Tokens/sec | 9.2 | 38.1 |
| GT overlap | 0.300 | 0.500 |
| Refusal | False | False |

---

### Prompt 4 (ID: 5a8048405542995d8a8ddf57)

**Question:** "Candy" is a duet with Iggy Pop and Kate Pierson, an American vocalist, lyricist, and one of the singers and founding members of what group?

**Ground Truth:** The B-52's

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | The answer is The B-52's. | The answer is The B-52's. |
| Tokens | 4990 | 4990 |
| Prompt tokens | 4980 | 4980 |
| Completion tokens | 10 | 10 |
| Gen time | 1.9937s | 0.2590s |
| Tokens/sec | 5.0 | 38.6 |
| GT overlap | 0.200 | 0.200 |
| Refusal | False | False |

---

### Prompt 5 (ID: 5a7f3a035542992e7d278ca1)

**Question:** What band formed in Knoxville Tennessee in 1999 released its first single to iTunes in 2008?

**Ground Truth:** 10 Years

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot verify which band formed in Knoxville, Tennessee in 1999 and released its first single to iTunes in 2008. | I couldn't find any information about a band that formed in Knoxville, Tennessee in 1999 and released its first single to iTunes in 2008. |
| Tokens | 5322 | 3744 |
| Prompt tokens | 5295 | 3712 |
| Completion tokens | 27 | 32 |
| Gen time | 2.6589s | 0.7844s |
| Tokens/sec | 10.2 | 40.8 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | False |

---

### Prompt 6 (ID: 5ae0d72d55429945ae95947c)

**Question:** The viola organista is a musical instrument designed by Leonardo da Vinci, was an Italian Renaissance polymath whose areas of interest included invention, painting, sculpting, architecture, science, music, mathematics, engineering, literature, anatomy, geology, astronomy, botany, writing, history, a...

**Ground Truth:** 1519

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | The answer is not explicitly stated in the provided context. The context only mentions Leonardo da Vinci's birth and death years (1452-1519), but does not specify the exact year of his death. | The answer is not explicitly stated in the provided context. The context only mentions Leonardo da Vinci's birth and death years (1452-1519), but does not provide the year of his death. |
| Tokens | 3818 | 3817 |
| Prompt tokens | 3776 | 3776 |
| Completion tokens | 42 | 41 |
| Gen time | 2.2898s | 0.8766s |
| Tokens/sec | 18.3 | 46.8 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 7 (ID: 5a8ac4e455429970aeb70308)

**Question:** Who did George Sanders play in Alfred Hitchcock's first American project?

**Ground Truth:** Jack Favell

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I do not have enough context to answer your question. | Unfortunately, the provided context does not contain information about George Sanders' role in Alfred Hitchcock's first American project. |
| Tokens | 3299 | 2345 |
| Prompt tokens | 3287 | 2321 |
| Completion tokens | 12 | 24 |
| Gen time | 1.5351s | 0.5050s |
| Tokens/sec | 7.8 | 47.5 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 8 (ID: 5a88a3695542997e5c09a661)

**Question:** Who costarred as John Carroll Lynch's brother in his most recent film?

**Ground Truth:** Nick Offerman

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I do not have enough information to answer this question. | I do not have enough information to provide an answer to the question. |
| Tokens | 4028 | 2895 |
| Prompt tokens | 4016 | 2880 |
| Completion tokens | 12 | 15 |
| Gen time | 1.6712s | 0.3627s |
| Tokens/sec | 7.2 | 41.4 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 9 (ID: 5ade90cb5542992fa25da7cd)

**Question:** Anetta Kahane is a former agent for the official state security service of the German Democratic Republic which was headquartered where?

**Ground Truth:** East Berlin

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Anetta Kahane was a former agent for the official state security service of the German Democratic Republic, which was headquartered in East Berlin. | The official state security service of the German Democratic Republic, commonly known as the Stasi, was headquartered in East Berlin. |
| Tokens | 4593 | 2839 |
| Prompt tokens | 4565 | 2814 |
| Completion tokens | 28 | 25 |
| Gen time | 2.2507s | 0.5676s |
| Tokens/sec | 12.4 | 44.0 |
| GT overlap | 0.045 | 0.053 |
| Refusal | False | False |

---

### Prompt 10 (ID: 5ae2057b554299234fd043a5)

**Question:** Which is an indie band, Days of the New or Archers of Loaf?

**Ground Truth:** Archers of Loaf

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Archers of Loaf. | Archers of Loaf. |
| Tokens | 3744 | 2564 |
| Prompt tokens | 3737 | 2557 |
| Completion tokens | 7 | 7 |
| Gen time | 1.6307s | 0.1921s |
| Tokens/sec | 4.3 | 36.4 |
| GT overlap | 0.500 | 0.500 |
| Refusal | False | False |

---

### Prompt 11 (ID: 5a8793a75542996e4f30884b)

**Question:** Are Rivers Cuomo and Peter Cox both from England?

**Ground Truth:** no

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | There is no information provided in the context about Rivers Cuomo or Peter Cox. | No, the question does not mention Rivers Cuomo or Peter Cox. |
| Tokens | 5462 | 3501 |
| Prompt tokens | 5446 | 3487 |
| Completion tokens | 16 | 14 |
| Gen time | 2.6797s | 0.3486s |
| Tokens/sec | 6.0 | 40.2 |
| GT overlap | 0.071 | 0.000 |
| Refusal | True | False |

---

### Prompt 12 (ID: 5a7bc8f955429927d897c043)

**Question:** The 2009 Hong Kong film Look for a Star was inspired by the lives of two people one of whom was born in 1921 and has what nickname?

**Ground Truth:** The King of Gambling

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I can answer the question based on the provided context. However, I need more information about the 2009 Hong Kong film "Look for a Star" to determine the nickname of the person it was inspired by. Th... | Unfortunately, the provided context does not contain enough information to answer the question. The context mentions the 2009 Hong Kong film "Look for a Star" but does not provide any information abou... |
| Tokens | 3505 | 2569 |
| Prompt tokens | 3432 | 2518 |
| Completion tokens | 73 | 51 |
| Gen time | 3.1191s | 1.0936s |
| Tokens/sec | 23.4 | 46.6 |
| GT overlap | 0.043 | 0.057 |
| Refusal | False | False |

---

### Prompt 13 (ID: 5ae0eb0e554299422ee99556)

**Question:** Who is the brother of the person who Dan Bobish lost to on October 19, 2007?

**Ground Truth:** Fedor Emelianenko

| Metric | System A (k=3) | System B (k=1) |
|--------|----------------|----------------|
| Answer | I cannot verify who Dan Bobish lost to on October 19, 2007. | I cannot verify the information about Dan Bobish. |
| Tokens | 5472 | 1977 |
| Prompt tokens | 5453 | 1966 |
| Completion tokens | 19 | 11 |
| Gen time | 3.1582s | 0.4950s |
| Tokens/sec | 6.0 | 22.2 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | True |

---

### Prompt 14 (ID: 5ae01a61554299603e4183e8)

**Question:** Which actress from the film Drive is best known for her role as Joan Holloway in the AMC drama "Mad Men"?

**Ground Truth:** Christina Hendricks

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | Christina Hendricks. | Christina Hendricks. |
| Tokens | 3614 | 3614 |
| Prompt tokens | 3608 | 3608 |
| Completion tokens | 6 | 6 |
| Gen time | 1.6176s | 0.1586s |
| Tokens/sec | 3.7 | 37.8 |
| GT overlap | 0.333 | 0.333 |
| Refusal | False | False |

---

### Prompt 15 (ID: 5adfd77055429906c02daa64)

**Question:** What is the real name of the actress in American Satan who is a pornographic actress?

**Ground Truth:** Michelle Chapman

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I do not have enough information to provide the answer to the question. | The answer is not explicitly stated in the provided context. |
| Tokens | 2465 | 1760 |
| Prompt tokens | 2450 | 1748 |
| Completion tokens | 15 | 12 |
| Gen time | 1.3095s | 0.2592s |
| Tokens/sec | 11.5 | 46.3 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 16 (ID: 5a7e26645542995ed0d166af)

**Question:** Chungking Mansions is a building located at 36–44 Nathan Road in Tsim Sha Tsui, Kowloon, Hong Kong, the unusual atmosphere of the building is sometimes compared to that of the former Kowloon Walled City, Kowloon Walled City was a largely-ungoverned densely-populated settlement in Kowloon City in whi...

**Ground Truth:** Hong Kong

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Based on the provided context, I can answer the question as follows:

Chungking Mansions is a building located at 36–44 Nathan Road in Tsim Sha Tsui, Kowloon, Hong Kong. The unusual atmosphere of the ... | Based on the provided context, Kowloon Walled City was a largely-ungoverned densely-populated settlement in Kowloon City. |
| Tokens | 3508 | 2530 |
| Prompt tokens | 3426 | 2500 |
| Completion tokens | 82 | 30 |
| Gen time | 3.1824s | 0.6389s |
| Tokens/sec | 25.8 | 47.0 |
| GT overlap | 0.021 | 0.000 |
| Refusal | False | False |

---

### Prompt 17 (ID: 5ae075c65542993d6555eb5e)

**Question:** Colin Campbell was replaced as NHL Senior Vice President by which president of the Toronto Maple Leafs?

**Ground Truth:** Brendan Frederick Shanahan

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot verify who replaced Colin Campbell as NHL Senior Vice President. | Unfortunately, the provided context does not contain information about Colin Campbell being replaced as NHL Senior Vice President by a president of the Toronto Maple Leafs. |
| Tokens | 5642 | 3529 |
| Prompt tokens | 5628 | 3500 |
| Completion tokens | 14 | 29 |
| Gen time | 2.4191s | 0.6633s |
| Tokens/sec | 5.8 | 43.7 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | False |

---

### Prompt 18 (ID: 5a77d6835542995d83181302)

**Question:** Circa Waves and The Gandharvas, have what in common?

**Ground Truth:** rock band

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I do not have enough context to answer this question. | I don't have enough context to answer the question. The provided text appears to be about Sanskrit Upanishads and Carnatic music ragas, but it does not mention Circa Waves or The Gandharvas. |
| Tokens | 4610 | 3035 |
| Prompt tokens | 4598 | 2989 |
| Completion tokens | 12 | 46 |
| Gen time | 2.0950s | 0.9830s |
| Tokens/sec | 5.7 | 46.8 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 19 (ID: 5a8b25c855429950cd6afc57)

**Question:** What "Census" conservation project did the group that backed Value America also fund?

**Ground Truth:** the Great Elephant Census

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot find any information about a "Census" conservation project funded by the group that backed Value America. | I cannot provide information about a potential census conservation project funded by the group that backed Value America. Is there anything else I can help you with? |
| Tokens | 4455 | 2493 |
| Prompt tokens | 4432 | 2463 |
| Completion tokens | 23 | 30 |
| Gen time | 2.1704s | 0.6309s |
| Tokens/sec | 10.6 | 47.5 |
| GT overlap | 0.048 | 0.071 |
| Refusal | True | True |

---

### Prompt 20 (ID: 5a8ec75c55429917b4a5bdc2)

**Question:** Randolph Bromery was a member of a group of airmen that formed which groups of the United States Army Air forces ?

**Ground Truth:** the 332nd Fighter Group and the 477th Bombardment Group

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | Unfortunately, the provided context does not mention Randolph Bromery being a member of any specific group of airmen. The context only mentions that Randolph Bromery was a member of the Tuskegee Airme... | Unfortunately, the provided context does not mention Randolph Bromery being a member of any specific group of airmen within the United States Army Air Forces. |
| Tokens | 5600 | 5567 |
| Prompt tokens | 5536 | 5536 |
| Completion tokens | 64 | 31 |
| Gen time | 3.7791s | 0.8485s |
| Tokens/sec | 16.9 | 36.5 |
| GT overlap | 0.051 | 0.071 |
| Refusal | False | False |

---

### Prompt 21 (ID: 5abc222a55429959677d6a20)

**Question:** The footballer sold to Arsenal by Olympique de Marseille in the 2000-01 season was of which nationality?

**Ground Truth:** French

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot find any information about a footballer sold to Arsenal by Olympique de Marseille in the 2000-01 season. | Unfortunately, the provided context does not contain information about the nationality of the footballer sold to Arsenal by Olympique de Marseille in the 2000-01 season. |
| Tokens | 3799 | 2614 |
| Prompt tokens | 3772 | 2580 |
| Completion tokens | 27 | 34 |
| Gen time | 2.1557s | 0.7166s |
| Tokens/sec | 12.5 | 47.4 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | False |

---

### Prompt 22 (ID: 5a7c61d455429907fabeef75)

**Question:** The actor who played John Aubrey in many productions of Brief Lives is also known for narrating the audio book versions of what series?

**Ground Truth:** "A Song of Ice and Fire"

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | Roy Dotrice. | Roy Dotrice. |
| Tokens | 3923 | 3923 |
| Prompt tokens | 3918 | 3918 |
| Completion tokens | 5 | 5 |
| Gen time | 1.5933s | 0.1366s |
| Tokens/sec | 3.1 | 36.6 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 23 (ID: 5ab841df55429934fafe6d3f)

**Question:** The 2010 SEC Women's Basketball Tournament was held in the Atlanta suburb with a 2010 population of what?

**Ground Truth:** 26,600

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | The 2010 SEC Women's Basketball Tournament was held in the Atlanta suburb of Duluth, Georgia, with a population of 26,600 as of the 2010 census. | I do not have enough information to answer the question. The provided context does not mention the 2010 SEC Women's Basketball Tournament or its location. |
| Tokens | 3316 | 2024 |
| Prompt tokens | 3278 | 1993 |
| Completion tokens | 38 | 31 |
| Gen time | 2.0763s | 0.6368s |
| Tokens/sec | 18.3 | 48.7 |
| GT overlap | 0.050 | 0.000 |
| Refusal | False | False |

---

### Prompt 24 (ID: 5a8165f75542995ce29dcbf8)

**Question:** Who created the TV drama in which the actor who plays as Zack Morris in Saved by the Bell, stars as an unconventional lawyer?

**Ground Truth:** Kevin Falls and Bill Chais

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | The actor who plays as Zack Morris in Saved by the Bell, Mark-Paul Gosselaar, stars as Peter Bash, an unconventional lawyer, in the TV drama "Franklin & Bash". | The actor who plays as Zack Morris in Saved by the Bell, Mark-Paul Gosselaar, stars as Peter Bash, an unconventional lawyer, in the TV drama "Franklin & Bash". |
| Tokens | 3158 | 3158 |
| Prompt tokens | 3117 | 3117 |
| Completion tokens | 41 | 41 |
| Gen time | 2.0365s | 0.8813s |
| Tokens/sec | 20.1 | 46.5 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 25 (ID: 5ac3817b554299741d48a26b)

**Question:** Who was elected President of Liberia after Bayjay won song of the year in 2005? Ellen Johnson Sirleaf

**Ground Truth:** Ellen Johnson Sirleaf

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | There is no information provided in the context that Bayjay won song of the year in 2005, or that this event led to Ellen Johnson Sirleaf being elected President of Liberia. | There is no information provided in the context about a person named Bayjay winning a song of the year award in 2005, or about a person named Ellen Johnson Sirleaf being elected President of Liberia a... |
| Tokens | 3760 | 2339 |
| Prompt tokens | 3722 | 2293 |
| Completion tokens | 38 | 46 |
| Gen time | 2.3688s | 0.9734s |
| Tokens/sec | 16.0 | 47.3 |
| GT overlap | 0.111 | 0.097 |
| Refusal | True | True |

---

### Prompt 26 (ID: 5a7a0c805542990783324e0f)

**Question:** Anja Nissen (born 6 November 1995), sometimes known as simply Anja, is a Danish-Australian singer, songwriter, dancer and actress, she lists her influences as Patti LaBelle, an American singer, author, actress, and entrepreneur, born when?

**Ground Truth:** May 24, 1944

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | The answer is not provided in the given context. | Unfortunately, the provided context does not contain enough information to determine the birth year of Patti LaBelle. |
| Tokens | 4651 | 3376 |
| Prompt tokens | 4640 | 3353 |
| Completion tokens | 11 | 23 |
| Gen time | 2.1755s | 0.5371s |
| Tokens/sec | 5.1 | 42.8 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 27 (ID: 5ade02e55542992200553bdf)

**Question:** Indian film actress, Kriti Kharbanda, stars in Minchagi Nee Baralu, but she made her acting debut what 2009 Telugu film?

**Ground Truth:** with the Telugu film "Boni"

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Unfortunately, the provided context does not contain information about Kriti Kharbanda's acting debut. | Unfortunately, the provided context does not mention Kriti Kharbanda or her acting debut. |
| Tokens | 4241 | 2904 |
| Prompt tokens | 4219 | 2883 |
| Completion tokens | 22 | 21 |
| Gen time | 2.2369s | 0.4698s |
| Tokens/sec | 9.8 | 44.7 |
| GT overlap | 0.059 | 0.059 |
| Refusal | False | False |

---

### Prompt 28 (ID: 5ae18f355542997283cd222e)

**Question:** What is the name of a recent executive order that would be opposed by Blair Amani?

**Ground Truth:** Executive Order 13769

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Unfortunately, the provided context does not mention Blair Imani's stance on a specific executive order. | Unfortunately, the provided context does not mention Blair Imani's stance on a specific executive order. However, based on her role as an activist and her involvement in the Black Lives Matter movemen... |
| Tokens | 3937 | 2654 |
| Prompt tokens | 3917 | 2592 |
| Completion tokens | 20 | 62 |
| Gen time | 2.0078s | 1.2899s |
| Tokens/sec | 10.0 | 48.1 |
| GT overlap | 0.059 | 0.021 |
| Refusal | False | False |

---

### Prompt 29 (ID: 5a7a9d055542995eb53be87a)

**Question:** Which band was formed first, Grizzly Bear or Jesus Jones?

**Ground Truth:** Jesus Jones

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Based on the provided context, Jesus Jones was formed in late 1988, while Grizzly Bear was formed in 2002. Therefore, Jesus Jones was formed first. | Jesus Jones was formed first, in late 1988, while Grizzly Bear was formed in 2002. |
| Tokens | 3389 | 2591 |
| Prompt tokens | 3353 | 2567 |
| Completion tokens | 36 | 24 |
| Gen time | 2.0848s | 0.5201s |
| Tokens/sec | 17.3 | 46.1 |
| GT overlap | 0.111 | 0.167 |
| Refusal | False | False |

---

### Prompt 30 (ID: 5ab83e245542990e739ec889)

**Question:** Bob Gale co-wrote famously a movie starring Michael J. Fox was which character?

**Ground Truth:** Marty McFly

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | Doc Hollywood | Doc Hollywood. |
| Tokens | 3291 | 3292 |
| Prompt tokens | 3288 | 3288 |
| Completion tokens | 3 | 4 |
| Gen time | 1.3746s | 0.1084s |
| Tokens/sec | 2.2 | 36.9 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 31 (ID: 5ab583b45542992aa134a33c)

**Question:** Why did the author of the satire that features the fictional island of Luggnagg say he wrote it?

**Ground Truth:** "to vex the world rather than divert it"

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot answer your question as the context is insufficient. | I do not have enough context to answer the question. |
| Tokens | 3472 | 2033 |
| Prompt tokens | 3460 | 2021 |
| Completion tokens | 12 | 12 |
| Gen time | 1.6602s | 0.2709s |
| Tokens/sec | 7.2 | 44.3 |
| GT overlap | 0.059 | 0.059 |
| Refusal | True | False |

---

### Prompt 32 (ID: 5a8f59495542992414482a6e)

**Question:** How many pitches was the Major League Baseball player, who spent his entire career with the Houston Astros and ranked sixth in national league history in games played, hit by?

**Ground Truth:** 285

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot verify how many pitches the Major League Baseball player, who spent his entire career with the Houston Astros and ranked sixth in national league history in games played, was hit by. | I do not have enough information to answer the question. |
| Tokens | 5395 | 3703 |
| Prompt tokens | 5358 | 3691 |
| Completion tokens | 37 | 12 |
| Gen time | 3.0595s | 0.3041s |
| Tokens/sec | 12.1 | 39.5 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | False |

---

### Prompt 33 (ID: 5ae1def25542997f29b3c153)

**Question:** The first performance of the opera "Lord Byron" was choreophraphed by a man that was awarded the Spingarn Medal in what year?

**Ground Truth:** 1977

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Unfortunately, the provided context does not contain enough information to determine the year in which the choreographer who choreographed the first performance of the opera "Lord Byron" was awarded t... | Unfortunately, the provided context does not contain enough information to determine the year in which the choreographer was awarded the Spingarn Medal. |
| Tokens | 3649 | 2623 |
| Prompt tokens | 3608 | 2595 |
| Completion tokens | 41 | 28 |
| Gen time | 2.4760s | 0.6102s |
| Tokens/sec | 16.6 | 45.9 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 34 (ID: 5a8496075542997b5ce3fedc)

**Question:** RapidShare was an online file hosting service that opened in 2002, following the 2012 takedown of which similar service, a Hong Kong–based online company established in 2005 that operated from 2005 to 2012 providing online services related to file storage and viewing?

**Ground Truth:** Megaupload Ltd

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Based on the provided context, I was unable to find any information about RapidShare being compared to a specific online company that was takedown in 2012. | Based on the provided context, the answer is: RapidShare. |
| Tokens | 3605 | 2573 |
| Prompt tokens | 3572 | 2559 |
| Completion tokens | 33 | 14 |
| Gen time | 2.2260s | 0.3348s |
| Tokens/sec | 14.8 | 41.8 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | False |

---

### Prompt 35 (ID: 5ae684475542991bbc97610d)

**Question:** Which South Korean actress born in 1999 acted in Because I Love You?

**Ground Truth:** Kim Yoo-jung

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Kim Yoo-jung (born September 22, 1999) acted in Because I Love You. | Kim Yoo-jung. |
| Tokens | 3876 | 3101 |
| Prompt tokens | 3853 | 3094 |
| Completion tokens | 23 | 7 |
| Gen time | 2.1411s | 0.1914s |
| Tokens/sec | 10.7 | 36.6 |
| GT overlap | 0.167 | 0.333 |
| Refusal | False | False |

---

### Prompt 36 (ID: 5ab2bea8554299166977408d)

**Question:** In which political party is the senator of the district of the New York Senate that contains a village which had a population of 3,103 at the time of the 2010 Census?

**Ground Truth:** He is a Republican.

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Unfortunately, the provided context does not contain enough information to answer the question. | I do not have enough information to answer the question. |
| Tokens | 3928 | 2812 |
| Prompt tokens | 3912 | 2800 |
| Completion tokens | 16 | 12 |
| Gen time | 2.0359s | 0.2946s |
| Tokens/sec | 7.9 | 40.7 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 37 (ID: 5adc383c554299438c868d7a)

**Question:** What is Sheree North correlation to the Bing Crosby Show?

**Ground Truth:** Guest stars

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Sheree North was an actress who appeared in the 1964-1965 television series "The Bing Crosby Show", playing the role of Ellie Collins, Bing Crosby's on-screen wife. | Unfortunately, the provided context does not mention Sheree North's correlation to the Bing Crosby Show. |
| Tokens | 3934 | 2448 |
| Prompt tokens | 3895 | 2428 |
| Completion tokens | 39 | 20 |
| Gen time | 2.5044s | 0.4392s |
| Tokens/sec | 15.6 | 45.5 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 38 (ID: 5a8fb76e55429918e830d2bc)

**Question:** The Saga of Baby Divine is a children's picture book, written by Bette Midler, an American singer, songwriter, actress, comedian, and film producer, born on which date?

**Ground Truth:** December 1, 1945

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | The Saga of Baby Divine is a children's picture book written by Bette Midler, an American singer, songwriter, actress, comedian, and film producer, born on December 1, 1945. | The Saga of Baby Divine is a children's picture book written by Bette Midler, an American singer, songwriter, actress, comedian, and film producer, born on December 1, 1945. |
| Tokens | 4860 | 4860 |
| Prompt tokens | 4817 | 4817 |
| Completion tokens | 43 | 43 |
| Gen time | 3.0404s | 1.0107s |
| Tokens/sec | 14.1 | 42.5 |
| GT overlap | 0.069 | 0.069 |
| Refusal | False | False |

---

### Prompt 39 (ID: 5add3d245542995b365faad5)

**Question:** What fighter nicknamed the Mandingo Warrior was coached by Ann Wolfe?

**Ground Truth:** James Kirkland

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot verify who coached the fighter nicknamed the Mandingo Warrior. | I cannot verify who was coached by Ann Wolfe. |
| Tokens | 4900 | 3236 |
| Prompt tokens | 4886 | 3225 |
| Completion tokens | 14 | 11 |
| Gen time | 2.6616s | 0.2911s |
| Tokens/sec | 5.3 | 37.8 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | True |

---

### Prompt 40 (ID: 5adfe3d055429925eb1afafc)

**Question:** Where was Honest Ed's s store located at in Canada?

**Ground Truth:** Toronto, Ontario

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot verify where Honest Ed's store was located in Canada. | There is no information provided in the context about Honest Ed's store location in Canada. |
| Tokens | 3019 | 2089 |
| Prompt tokens | 3005 | 2071 |
| Completion tokens | 14 | 18 |
| Gen time | 1.7103s | 0.3967s |
| Tokens/sec | 8.2 | 45.4 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | True |

---

### Prompt 41 (ID: 5ae11362554299422ee995fa)

**Question:** what does Ray Dorset and Brian May have in common?

**Ground Truth:** singer

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | There is not enough context provided to answer the question about what Ray Dorset and Brian May have in common. | There is not enough context provided to answer the question about what Ray Dorset and Brian May have in common. |
| Tokens | 2674 | 1665 |
| Prompt tokens | 2651 | 1642 |
| Completion tokens | 23 | 23 |
| Gen time | 1.7610s | 0.4893s |
| Tokens/sec | 13.1 | 47.0 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 42 (ID: 5a7df0425542995f4f402332)

**Question:** Tobias Alistair Patrick "Toby" Kebbell is known for his roles in films such as "Dead Man's Shoes" (2004), "RocknRolla" (2008), "" (2010), "War Horse" (2011), "Wrath of the Titans" (2012), "Dawn of the Planet of the Apes" (2014), "Fantastic Four" (2015),"Warcraft" (2016), a 2016 American action fanta...

**Ground Truth:** Duncan Jones

| Metric | System A (k=3) | System B (k=3) |
|--------|----------------|----------------|
| Answer | Toby Kebbell is known for his roles in films such as "Dead Man's Shoes" (2004), "RocknRolla" (2008), "" (2010), "War Horse" (2011), "Wrath of the Titans" (2012), "Dawn of the Planet of the Apes" (2014... | Toby Kebbell is known for his roles in films such as "Dead Man's Shoes" (2004), "RocknRolla" (2008), "" (2010), "War Horse" (2011), "Wrath of the Titans" (2012), "Dawn of the Planet of the Apes" (2014... |
| Tokens | 4321 | 4321 |
| Prompt tokens | 4217 | 4217 |
| Completion tokens | 104 | 104 |
| Gen time | 4.3892s | 2.3002s |
| Tokens/sec | 23.7 | 45.2 |
| GT overlap | 0.021 | 0.021 |
| Refusal | False | False |

---

### Prompt 43 (ID: 5ab7f20d55429928e1fe3952)

**Question:** What do Christopher Guest and Thomas Schlamme have in common?

**Ground Truth:** director

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I do not have enough information to answer the question. | There is no information provided about Christopher Guest and Thomas Schlamme in the given context. |
| Tokens | 3369 | 2229 |
| Prompt tokens | 3357 | 2210 |
| Completion tokens | 12 | 19 |
| Gen time | 1.7373s | 0.4129s |
| Tokens/sec | 6.9 | 46.0 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | True |

---

### Prompt 44 (ID: 5ab35241554299233954ff49)

**Question:** When was the American sports radio personality and pornographic actress born who parodied Sarah Palin in "Who's Nailin' Paylin?

**Ground Truth:** May 9, 1972

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | The question does not provide enough context to determine the answer. The provided text mentions several individuals with the name "Sarah Palin" or "Sarah Palin parody," but it does not specify which ... | I cannot verify the answer to your question. |
| Tokens | 2882 | 1586 |
| Prompt tokens | 2838 | 1576 |
| Completion tokens | 44 | 10 |
| Gen time | 2.0469s | 0.2236s |
| Tokens/sec | 21.5 | 44.7 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | True |

---

### Prompt 45 (ID: 5adde9015542992200553b9a)

**Question:** Richardson Square Mall includes a privately held regional fast-food chain based in what Texas city?

**Ground Truth:** San Antonio

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot verify the name of the privately held regional fast-food chain based in Richardson, Texas. | I cannot verify the information requested. |
| Tokens | 3474 | 2547 |
| Prompt tokens | 3454 | 2539 |
| Completion tokens | 20 | 8 |
| Gen time | 1.7952s | 0.1986s |
| Tokens/sec | 11.1 | 40.3 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | True |

---

### Prompt 46 (ID: 5ab1dbce5542993be8fa985b)

**Question:** Who is in unrequited love with the daughter of Egeus?

**Ground Truth:** Demetrius

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I do not have enough context to answer this question. | I do not have enough context to answer the question. |
| Tokens | 3934 | 2685 |
| Prompt tokens | 3922 | 2673 |
| Completion tokens | 12 | 12 |
| Gen time | 1.9228s | 0.2991s |
| Tokens/sec | 6.2 | 40.1 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

### Prompt 47 (ID: 5a7f754d5542992e7d278d07)

**Question:** The music video to Daft Punk Is Playing at My House paid homage to a 1995 single by Daft Punk and what other record?

**Ground Truth:** Around the World

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I couldn't find any information about a music video called "Daft Punk Is Playing at My House". | The context does not provide enough information to answer the question. |
| Tokens | 3854 | 2761 |
| Prompt tokens | 3832 | 2748 |
| Completion tokens | 22 | 13 |
| Gen time | 2.0637s | 0.3000s |
| Tokens/sec | 10.7 | 43.3 |
| GT overlap | 0.000 | 0.083 |
| Refusal | False | False |

---

### Prompt 48 (ID: 5a845ec85542996488c2e535)

**Question:** Iru Mugan stars the actress who has won which two awards for her work?

**Ground Truth:** Filmfare Awards

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Nithya Menen. | Nithya Menen stars in the film Iru Mugan. She won two Filmfare Awards for the Telugu films "Gunde Jaari Gallanthayyinde" and "Malli Malli Idi Rani Roju". |
| Tokens | 4294 | 3054 |
| Prompt tokens | 4287 | 3004 |
| Completion tokens | 7 | 50 |
| Gen time | 1.9116s | 1.0777s |
| Tokens/sec | 3.7 | 46.4 |
| GT overlap | 0.000 | 0.080 |
| Refusal | False | False |

---

### Prompt 49 (ID: 5ab76fee5542993667793fdd)

**Question:** Who wrote this book set in the Land of Oz in which the shite kitten Eureka is introduced?

**Ground Truth:** L. Frank Baum

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | I cannot verify who wrote the book set in the Land of Oz that features a shite kitten named Eureka. | I cannot verify who wrote the book set in the Land of Oz with the shite kitten Eureka. |
| Tokens | 4234 | 2547 |
| Prompt tokens | 4210 | 2525 |
| Completion tokens | 24 | 22 |
| Gen time | 2.3273s | 0.4906s |
| Tokens/sec | 10.3 | 44.8 |
| GT overlap | 0.000 | 0.000 |
| Refusal | True | True |

---

### Prompt 50 (ID: 5a886cdd55429938390d3f57)

**Question:** What band's drummer assembled the compilation A New Wave of Brith Heavy Metal '79 Revisited?

**Ground Truth:** Metallica

| Metric | System A (k=3) | System B (k=2) |
|--------|----------------|----------------|
| Answer | Lars Ulrich, the drummer of Metallica, assembled the compilation "New Wave of British Heavy Metal '79 Revisited". | The band's drummer who assembled the compilation "A New Wave of British Heavy Metal '79 Revisited" is Lars Ulrich, the drummer and co-founder of Metallica. |
| Tokens | 4190 | 3063 |
| Prompt tokens | 4163 | 3027 |
| Completion tokens | 27 | 36 |
| Gen time | 2.3727s | 0.8197s |
| Tokens/sec | 11.4 | 43.9 |
| GT overlap | 0.000 | 0.000 |
| Refusal | False | False |

---

