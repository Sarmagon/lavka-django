/* Original Lavka storefront: same-origin Django API, no third-party libraries. */
"use strict";
const $ = (selector) => document.querySelector(selector);
const page = document.body.dataset.page;
const money = (value) => new Intl.NumberFormat("ru-RU", {style:"currency", currency:"RUB", maximumFractionDigits:2}).format(value);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let noticeTimer;
function notice(text) { $("#notice").textContent=text; clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>$("#notice").textContent="",5000); }
function csrf() { return decodeURIComponent(document.cookie.split("; ").find(v=>v.startsWith("csrftoken="))?.split("=").slice(1).join("=") || ""); }
async function api(url, method="GET", data) {
  const headers={"Accept":"application/json"}; const options={method, headers, credentials:"same-origin"};
  if(method!=="GET") { headers["X-CSRFToken"]=csrf(); if(data instanceof FormData) options.body=data; else {headers["Content-Type"]="application/json"; options.body=JSON.stringify(data ?? {});} }
  const response=await fetch(url,options); let body; try {body=await response.json();} catch {throw new Error("Не удалось получить ответ. Обновите страницу и повторите.");}
  if(!response.ok) {const error=new Error(Object.values(body.errors || {}).flat().join(" ") || "Не удалось выполнить действие."); error.status=response.status; throw error;} return body;
}
function art(product, className="") {
  const image=product.images?.[0]; if(image?.sheet) return `<div class="product-art ${className}" role="img" aria-label="${escapeHTML(image.alt)}" style="background-image:url('${escapeHTML(image.src)}');background-position:${["left top","right top","left bottom","right bottom"][image.cell] || "left top"}"></div>`;
  return `<img class="${className}" src="${escapeHTML(image?.src || '/static/catalog/placeholder.svg')}" alt="${escapeHTML(image?.alt || product.title)}" loading="lazy">`;
}
function price(product) {return `<span class="price">${money(product.salePrice ?? product.price)}${product.discountPercent ? `<del>${money(product.oldPrice ?? product.price)}</del>`:""}</span>`;}
function card(product) {return `<article class="card">${product.discountPercent?`<span class="tag">−${product.discountPercent}%</span>`:""}<a class="card-image" href="/product/${product.id}/">${art(product)}</a><h3><a href="/product/${product.id}/">${escapeHTML(product.title)}</a></h3><p>${escapeHTML(product.manufacturer)} · ${product.count ? "В наличии":"Нет в наличии"}</p><div class="price-row">${price(product)}<button class="add" data-add="${product.id}" ${!product.count?"disabled":""}>В корзину</button></div></article>`;}
function renderProducts(items) {$("#products").innerHTML=items.length ? items.map(card).join("") : '<div class="empty">Ничего не найдено. Попробуйте изменить фильтры.</div>';}
function basketCount(rows) {$("#basket-count").textContent=rows.reduce((sum,p)=>sum+p.count,0);}
async function updateBasket() {basketCount(await api('/api/basket'));}
function bindForm(selector, handler) {
  const form=$(selector); if(!form)return; form.addEventListener("submit",async event=>{event.preventDefault();const button=form.querySelector('button[type=submit],button:not([type])'); const error=form.querySelector('.form-error'); if(error)error.textContent="";if(button)button.disabled=true;
    try{await handler(Object.fromEntries(new FormData(form)),form);}catch(e){if(error)error.textContent=e.message;else notice(e.message);}finally{if(button)button.disabled=false;}});
}
function safeNext() {const value=new URLSearchParams(location.search).get('next'); return value?.startsWith('/')&&!value.startsWith('//')&&!value.includes('\\') ? value:'/profile/';}
async function categories() {const result=await api('/api/categories'); const select=$('#category'); for(const category of result.flatMap(c=>[c,...c.subcategories])) {const option=document.createElement('option');option.value=category.id;option.textContent=category.title;select.append(option);} }
let catalogPage=1;
async function loadCatalog(number=1) {
  catalogPage=number;const filters=new FormData($('#filters'));const params=new URLSearchParams({currentPage:number,limit:12,sort:'price'});for(const [k,v] of filters.entries()){if(v)params.append(k,v);}
  const result=await api(`/api/${page==='sale'?'sales':'catalog'}?${params}`);renderProducts(result.items);$('#result-count').textContent=`Найдено товаров: ${result.total}`;$('#pagination').innerHTML=Array.from({length:result.lastPage},(_,i)=>`<button data-catalog-page="${i+1}" ${i+1===number?'aria-current="page"':''}>${i+1}</button>`).join('');
}
function basketRows(rows) {return rows.map(p=>`<article class="basket-row"><a href="/product/${p.id}/">${art(p)}</a><div><h3><a href="/product/${p.id}/">${escapeHTML(p.title)}</a></h3><small>${money(p.price)} за штуку</small><div class="quantity"><button data-change="${p.id}" data-method="DELETE" aria-label="Уменьшить количество ${escapeHTML(p.title)}">−</button><span>${p.count}</span><button data-change="${p.id}" data-method="POST" aria-label="Увеличить количество ${escapeHTML(p.title)}">+</button><button class="secondary" data-change="${p.id}" data-method="DELETE" data-count="${p.count}">Удалить</button></div></div><span class="price">${money(p.price*p.count)}</span></article>`).join('');}
async function loadCart() {const rows=await api('/api/basket');basketCount(rows);$('#cart').innerHTML=rows.length?basketRows(rows)+`<div class="total"><span>Стоимость товаров <strong>${money(rows.reduce((s,p)=>s+p.price*p.count,0))}</strong><br><small>Доставка рассчитывается при оформлении.</small></span><a class="button" href="/checkout/">Оформить заказ →</a></div>`:'<div class="empty"><h2>Здесь пока тихо</h2><p>Добавьте вещи, которые вам понравились.</p><a class="button" href="/catalog/">В каталог →</a></div>';}
const productId=document.body.dataset.product;
let reviewPage=1;
function reviewHTML(review) {return `<article class="review"><strong>${escapeHTML(review.author)}</strong> · ${escapeHTML(review.rate)}/5<p>${escapeHTML(review.text)}</p><small>${new Date(review.date).toLocaleDateString('ru-RU')}</small></article>`;}
async function loadReviews(number=1) {reviewPage=number;const result=await api(`/api/product/${productId}/reviews?currentPage=${number}`);if(number===1)$('#reviews').innerHTML='';$('#reviews').insertAdjacentHTML('beforeend',result.items.map(reviewHTML).join('') || '<p>Пока нет отзывов.</p>');$('#more-reviews').hidden=number>=result.lastPage;}
async function loadProduct() {const p=await api(`/api/product/${productId}`);$('#product-detail').innerHTML=`<section class="detail"><div class="card-image">${art(p)}</div><div><p class="eyebrow">${escapeHTML(p.manufacturer)}</p><h1>${escapeHTML(p.title)}</h1><p class="description">${escapeHTML(p.fullDescription)}</p><p>${p.reviewCount} отзывов · ${p.rating}/5</p>${price(p)}<p><button data-add="${p.id}" ${!p.count?'disabled':''}>${p.count?'Добавить в корзину':'Нет в наличии'}</button></p><small>Учебный товар · иллюстративное изображение</small><table>${p.specifications.map(s=>`<tr><td>${escapeHTML(s.name)}</td><td>${escapeHTML(s.value)}</td></tr>`).join('')}</table><details><summary>Предложения продавцов</summary>${p.offers.map(o=>`<p>${escapeHTML(o.seller)} · ${money(o.price)} · ${o.stock} шт.</p>`).join('')}<small>Корзина выбирает доступное предложение с минимальной ценой; скидка рассчитывается сервером.</small></details></div></section>`;$('#review-form').hidden=!p.canReview;$('#review-login').innerHTML=p.canReview?'':'<a href="/sign-in/">Войдите</a>, чтобы оставить отзыв.';await loadReviews();}
let checkoutData;
async function loadCheckout() {checkoutData=await api('/api/checkout'); const rows=checkoutData.products;$('#checkout-summary').innerHTML=rows.length?`<p>${rows.length} позиций · товары на ${money(rows.reduce((s,p)=>s+p.price*p.count,0))}</p>`:'<div class="empty">Корзина пуста. <a href="/catalog/">Перейти в каталог →</a></div>';$('#checkout-form').hidden=!rows.length||!checkoutData.user;$('#checkout-register').hidden=!rows.length||Boolean(checkoutData.user);if(checkoutData.user){const profile=await api('/api/profile');for(const key of ['fullName','email','phone'])$('#checkout-form').elements[key].value=profile[key] || ''; } deliveryPreview();}
function deliveryPreview(){if(!checkoutData)return;const kind=$('#checkout-form').elements.deliveryType.value;$('#delivery-preview').textContent=`Доставка: ${money(kind==='express'?checkoutData.expressCost:checkoutData.ordinaryCost)}. Итоговая сумма будет рассчитана сервером.`;}
function orderHTML(o) {return `<article class="order-card"><p class="eyebrow">${new Date(o.createdAt).toLocaleDateString('ru-RU')}</p><h2>Заказ №${o.id}</h2><span class="status">${escapeHTML(o.status)}</span><p>${escapeHTML(o.city)} · ${escapeHTML(o.address)}</p><ul>${o.products.map(p=>`<li>${escapeHTML(p.title)} × ${p.count} — ${money(p.price*p.count)}</li>`).join('')}</ul><p>Доставка: ${money(o.deliveryCost)}</p><strong>Итого: ${money(o.totalCost)}</strong>${o.paymentError?`<p class="order-error">${escapeHTML(o.paymentError)}</p>`:''}<br><a href="/orders/${o.id}/">Открыть заказ →</a></article>`;}
function orderId(){return location.pathname.match(/\/(?:orders|order-detail|payment)\/(\d+)/)?.[1] || new URLSearchParams(location.search).get('order');}
async function loadOrder(){const o=await api(`/api/order/${orderId()}`);$('#order-detail').innerHTML=orderHTML(o);$('#payment-form').hidden=['paid','payment'].includes(o.statusCode);$('#payment-form').elements.paymentType.value=o.paymentType;if(o.statusCode==='payment')$('#order-detail').insertAdjacentHTML('beforeend','<p>Оплата в очереди. Обновите статус после обработки worker.</p>');}
async function loadProfile(){const p=await api('/api/profile');for(const key of ['fullName','email','phone'])$('#profile-form').elements[key].value=p[key]||'';const image=$('#avatar');image.hidden=!p.avatar;if(p.avatar)image.src=p.avatar.src;}
document.addEventListener('click',async event=>{const button=event.target.closest('[data-add],[data-change],[data-catalog-page]');if(!button)return;button.disabled=true;try{if(button.dataset.add){const rows=await api('/api/basket','POST',{id:Number(button.dataset.add),count:1});basketCount(rows);notice('Добавлено в корзину');}else if(button.dataset.change){await api('/api/basket',button.dataset.method,{id:Number(button.dataset.change),count:Number(button.dataset.count||1)});await loadCart();}else await loadCatalog(Number(button.dataset.catalogPage));}catch(e){notice(e.message);}finally{button.disabled=false;}});
bindForm('#auth-form',async data=>{await api(`/api/${page==='signUp'?'sign-up':'sign-in'}`,'POST',data);location.assign(safeNext());});
bindForm('#filters',async()=>loadCatalog());
bindForm('#review-form',async(data,form)=>{data.rate=Number(data.rate);await api(`/api/product/${productId}/reviews`,'POST',data);form.reset();await loadProduct();notice('Отзыв опубликован');});
bindForm('#profile-form',async data=>{await api('/api/profile','POST',data);notice('Профиль сохранён');});
bindForm('#password-form',async(data,form)=>{await api('/api/profile/password','POST',data);form.reset();notice('Пароль изменён');});
bindForm('#avatar-form',async(data,form)=>{await api('/api/profile/avatar','POST',new FormData(form));await loadProfile();notice('Аватар обновлён');});
bindForm('#checkout-register',async data=>{await api('/api/checkout/register','POST',data);await loadCheckout();notice('Аккаунт создан');});
bindForm('#checkout-form',async data=>{const o=await api('/api/orders','POST',{...data,checkoutKey:checkoutData.checkoutKey});location.assign(`/orders/${o.orderId}/`);});
bindForm('#payment-form',async data=>{await api(`/api/payment/${orderId()}`,'POST',data);await loadOrder();notice('Учебная оплата поставлена в очередь');});
$('#more-reviews')?.addEventListener('click',()=>loadReviews(reviewPage+1).catch(e=>notice(e.message)));
$('#refresh-order')?.addEventListener('click',()=>loadOrder().catch(e=>notice(e.message)));
$('#checkout-form')?.elements.deliveryType.addEventListener('change',deliveryPreview);
$('#logout')?.addEventListener('click',async()=>{try{await api('/api/sign-out','POST');location.assign('/');}catch(e){notice(e.message);}});
$('#remove-avatar')?.addEventListener('click',async()=>{try{await api('/api/profile/avatar','DELETE');await loadProfile();}catch(e){notice(e.message);}});
async function start(){await updateBasket();if(page==='index'){const data=await api('/api/catalog?limit=4&sort=date&sortType=inc');renderProducts(data.items);}if(['catalog','sale'].includes(page)){await categories();await loadFilterChoices();await loadCatalog();}if(page==='product')await loadProduct();if(page==='cart')await loadCart();if(page==='checkout')await loadCheckout();if(page==='profile')await loadProfile();if(page==='history'){const orders=await api('/api/orders');$('#orders').innerHTML=orders.length?orders.map(orderHTML).join(''):'<div class="empty">Заказов пока нет. <a href="/catalog/">В каталог →</a></div>';}if(page==='order')await loadOrder();}
start().catch(e=>{if(e.status===401){location.assign(`/sign-in/?next=${encodeURIComponent(location.pathname+location.search)}`);}else{notice(e.message);const container=$('#products');if(container)container.innerHTML='<p>Не удалось загрузить товары. Обновите страницу.</p>';}});

async function loadFilterChoices() {
  const category=$('#category').value;
  const data=await api('/api/catalog/filters'+(category?'?category='+encodeURIComponent(category):''));
  $('#manufacturer').innerHTML='<option value="">Все</option>'+data.manufacturers.map(m=>`<option value="${escapeHTML(m)}">${escapeHTML(m)}</option>`).join('');
  $('#attributes').innerHTML=data.attributes.map(a=>{
    const name=`attributes[${a.id}]`;
    if(a.kind==='text')return `<label>${escapeHTML(a.name)}<input name="${name}" maxlength="500" placeholder="Любой"></label>`;
    if(a.kind==='boolean')return `<label>${escapeHTML(a.name)}<select name="${name}"><option value="">Не важно</option><option value="true">Да</option><option value="false">Нет</option></select></label>`;
    return `<label>${escapeHTML(a.name)}<select name="${name}${a.kind==='multiple'?'[]':''}" ${a.kind==='multiple'?'multiple':''}><option value="">Любой</option>${a.options.map(o=>`<option value="${o.id}">${escapeHTML(o.value)}</option>`).join('')}</select></label>`;
  }).join('');
}
$('#category')?.addEventListener('change',()=>loadFilterChoices().catch(e=>notice(e.message)));
